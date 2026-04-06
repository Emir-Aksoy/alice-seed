#!/usr/bin/env python3
"""
Alice Seed Incremental
Create delta backups that store only files changed since the parent seed.
"""

import sys
import json
import zipfile
import argparse
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from config import get_profile

SEED_VERSION = "2.0.0"


class Colors:
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"


def _print(text: str, color: str = Colors.RESET) -> None:
    print(f"{color}{text}{Colors.RESET}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_seed_from_zip(path: Path) -> Optional[dict]:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names  = zf.namelist()
            target = "seed.json" if "seed.json" in names else next(
                (n for n in names if n.endswith(".json")), None
            )
            if target is None:
                return None
            return json.loads(zf.read(target))
    except Exception:
        return None


def _load_seed(path: Path) -> Optional[dict]:
    if path.suffix == ".zip":
        return _load_seed_from_zip(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _compute_changes(
    parent: dict, current: dict
) -> Dict[str, List[str]]:
    p_files = parent.get("files", {})
    c_files = current.get("files", {})

    added    = [f for f in c_files if f not in p_files]
    modified = [f for f in c_files if f in p_files and c_files[f] != p_files[f]]
    deleted  = [f for f in p_files if f not in c_files]

    return {"added": added, "modified": modified, "deleted": deleted}


# ── Create ────────────────────────────────────────────────────────────────────

def create_incremental_seed(
    parent_file: str,
    output_file: Optional[str] = None,
    agent: Optional[str] = None,
) -> bool:
    _print("\n📊 Creating incremental backup…", Colors.BOLD)
    print("=" * 60)

    parent_path = Path(parent_file)
    if not parent_path.exists():
        _print(f"❌ Parent seed not found: {parent_file}", Colors.RED)
        return False

    parent_seed = _load_seed(parent_path)
    if parent_seed is None:
        _print("❌ Cannot parse parent seed", Colors.RED)
        return False

    parent_id = parent_seed.get("meta", {}).get("seed_id", "unknown")
    _print(f"  Parent: {parent_path.name}  (id={parent_id})", Colors.BLUE)

    # Import here to keep sys.path correct
    from seed_generator import collect_seed_data
    current = collect_seed_data(agent)

    changes = _compute_changes(parent_seed, current)
    _print(
        f"\n  Added   : {len(changes['added'])}\n"
        f"  Modified: {len(changes['modified'])}\n"
        f"  Deleted : {len(changes['deleted'])}",
    )

    if not any(changes.values()):
        _print("\n✅ No changes — incremental backup not needed", Colors.GREEN)
        return True

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    seed_id   = f"inc_{timestamp}"

    delta_files = {
        f: current["files"][f]
        for f in changes["added"] + changes["modified"]
        if f in current["files"]
    }

    incremental_seed = {
        "header": {
            "version":            SEED_VERSION,
            "type":               "incremental",
            "seed_id":            seed_id,
            "parent_seed_id":     parent_id,
            "created":            datetime.now().isoformat(),
            "changes":            changes,
        },
        "files": delta_files,
        "meta": {
            "seed_version":        SEED_VERSION,
            "created_at":          datetime.now().isoformat(),
            "parent_created_at":   parent_seed.get("meta", {}).get("created_at"),
            "incremental":         True,
        },
    }

    profile = get_profile(agent)
    out = Path(output_file) if output_file else (
        profile["output_dir"] / f"alice_seed_incremental_{timestamp}.zip"
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("seed.json", json.dumps(incremental_seed, ensure_ascii=False, indent=2))

    _print(f"\n✅ Incremental seed: {out.name}", Colors.GREEN)
    _print(f"   Size   : {out.stat().st_size / 1024:.2f} KB", Colors.BLUE)
    _print(f"   Seed ID: {seed_id}", Colors.YELLOW)
    return True


# ── Apply ─────────────────────────────────────────────────────────────────────

def apply_incremental_seed(
    base_file: str,
    incremental_file: str,
    output_file: Optional[str] = None,
) -> bool:
    _print("\n📥 Applying incremental seed…", Colors.BOLD)
    print("=" * 60)

    base_seed = _load_seed(Path(base_file))
    inc_seed  = _load_seed(Path(incremental_file))

    if base_seed is None:
        _print(f"❌ Cannot read base seed: {base_file}", Colors.RED)
        return False
    if inc_seed is None:
        _print(f"❌ Cannot read incremental seed: {incremental_file}", Colors.RED)
        return False

    _print(f"  Base       : {Path(base_file).name}")
    _print(f"  Incremental: {Path(incremental_file).name}")

    changes  = inc_seed.get("header", {}).get("changes", {})
    _print(
        f"\n  Changes: {len(changes.get('added', []))} added, "
        f"{len(changes.get('modified', []))} modified, "
        f"{len(changes.get('deleted', []))} deleted"
    )

    base_files = base_seed.get("files", {})
    inc_files  = inc_seed.get("files", {})

    for f in changes.get("added", []) + changes.get("modified", []):
        if f in inc_files:
            base_files[f] = inc_files[f]

    for f in changes.get("deleted", []):
        base_files.pop(f, None)

    base_seed["files"] = base_files
    base_seed.setdefault("meta", {})["last_merged_at"] = datetime.now().isoformat()
    base_seed["meta"]["seed_version"] = SEED_VERSION

    if output_file:
        out = Path(output_file)
    else:
        stem = Path(base_file).stem
        out  = Path(base_file).with_name(f"{stem}_merged.zip")

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("seed.json", json.dumps(base_seed, ensure_ascii=False, indent=2))

    _print(f"\n✅ Merged seed: {out.name}", Colors.GREEN)
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Alice Seed incremental backup tool")
    sub    = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", help="Create incremental backup")
    p_create.add_argument("--parent", "-p", required=True, help="Parent seed file")
    p_create.add_argument("--output", "-o", help="Output file path")
    p_create.add_argument("--agent", "-a", choices=["nanobot", "claude"],
                          help="Agent profile")

    p_apply = sub.add_parser("apply", help="Merge incremental seed into base seed")
    p_apply.add_argument("--base",        "-b", required=True, help="Base seed file")
    p_apply.add_argument("--incremental", "-i", required=True, help="Incremental seed file")
    p_apply.add_argument("--output",      "-o", help="Output file path")

    args = parser.parse_args()
    if args.command == "create":
        ok = create_incremental_seed(args.parent, args.output,
                                     getattr(args, "agent", None))
    elif args.command == "apply":
        ok = apply_incremental_seed(args.base, args.incremental, args.output)
    else:
        parser.print_help()
        sys.exit(1)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
