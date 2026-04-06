#!/usr/bin/env python3
"""
Alice Seed Verify
Validate a seed file's structure, integrity, encryption state, and version.
"""

import sys
import json
import hashlib
import zipfile
import argparse
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

SUPPORTED_ALGOS = {"AES-256-GCM"}
CURRENT_MAJOR   = 2


class Colors:
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"


def _print(text: str, color: str = Colors.RESET) -> None:
    print(f"{color}{text}{Colors.RESET}")


# ── Individual checks ─────────────────────────────────────────────────────────

def check_structure(seed: dict) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []

    # Legacy format detection
    if "agents" in seed and "providers" in seed:
        issues.append(("info", "Legacy format detected (pre-v1.0)"))
        return issues

    for field in ("meta", "files"):
        if field not in seed:
            issues.append(("error", f"Missing required field: '{field}'"))

    if "meta" in seed:
        for field in ("seed_version", "created_at", "agent_name"):
            if field not in seed["meta"]:
                issues.append(("warning", f"meta is missing field: '{field}'"))

    return issues


def check_version(seed: dict) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    version = seed.get("meta", {}).get("seed_version", "unknown")
    try:
        major = int(str(version).split(".")[0])
        if major > CURRENT_MAJOR:
            issues.append((
                "warning",
                f"Seed version {version} is newer than this tool — some fields may be ignored",
            ))
    except (ValueError, IndexError):
        issues.append(("error", f"Cannot parse version: '{version}'"))
    return issues


def check_encryption(seed: dict) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    enc = seed.get("encrypted")

    if enc:
        for field in ("secrets", "salt", "nonce"):
            if field not in enc:
                issues.append(("warning", f"Encrypted block missing field: '{field}'"))

        algo = seed.get("header", {}).get("algo", "")
        if algo and algo not in SUPPORTED_ALGOS:
            issues.append((
                "error",
                f"Unsupported encryption algorithm: '{algo}'. "
                f"Supported: {SUPPORTED_ALGOS}",
            ))

        hint = seed.get("header", {}).get("key_hint", "")
        _print(f"  🔐 Encrypted seed  key_hint={hint or 'n/a'}", Colors.YELLOW)
    else:
        _print("  🔓 Unencrypted seed", Colors.BLUE)

    return issues


def check_hashes(seed: dict) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    file_hashes = seed.get("file_hashes", {})
    files       = seed.get("files", {})

    if not file_hashes:
        issues.append(("warning", "No file hashes stored — integrity cannot be verified"))
        return issues

    if len(file_hashes) != len(files):
        issues.append((
            "warning",
            f"Hash count ({len(file_hashes)}) ≠ file count ({len(files)})",
        ))

    # Verify stored content hashes
    for key, content in files.items():
        if key not in file_hashes or file_hashes[key] is None:
            continue
        computed = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if computed != file_hashes[key]:
            issues.append(("error", f"Hash mismatch for: {key}"))

    return issues


# ── Main entry ────────────────────────────────────────────────────────────────

def verify_seed_file(filepath: str, check_hash: bool = False) -> bool:
    _print(f"\n🔍 Verifying seed: {filepath}", Colors.BOLD)
    print("=" * 60)

    path = Path(filepath)
    if not path.exists():
        _print(f"❌ File not found: {filepath}", Colors.RED)
        return False

    _print(f"📄 Size: {path.stat().st_size / 1024:.2f} KB", Colors.BLUE)

    # ── Load ──────────────────────────────────────────────────────────────
    try:
        if filepath.endswith(".zip"):
            with zipfile.ZipFile(filepath, "r") as zf:
                names = zf.namelist()
                _print(f"📁 ZIP entries: {len(names)}", Colors.BLUE)
                target = "seed.json" if "seed.json" in names else next(
                    (n for n in names if n.endswith(".json")), None
                )
                if target is None:
                    _print("❌ No JSON file inside ZIP", Colors.RED)
                    return False
                seed = json.loads(zf.read(target))
        else:
            seed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _print(f"❌ JSON parse error: {exc}", Colors.RED)
        return False
    except Exception as exc:
        _print(f"❌ Could not read file: {exc}", Colors.RED)
        return False

    # ── Run checks ────────────────────────────────────────────────────────
    all_issues: List[Tuple[str, str]] = []

    _print("\n📋 Structure:", Colors.BOLD)
    issues = check_structure(seed)
    all_issues.extend(issues)
    for lvl, msg in issues:
        _print(f"  [{lvl.upper()}] {msg}", Colors.RED if lvl == "error" else Colors.YELLOW)
    if not issues:
        _print("  ✓ OK", Colors.GREEN)

    _print("\n🔗 Version:", Colors.BOLD)
    issues = check_version(seed)
    all_issues.extend(issues)
    for lvl, msg in issues:
        _print(f"  [{lvl.upper()}] {msg}", Colors.RED if lvl == "error" else Colors.YELLOW)
    if not issues:
        _print(f"  ✓ {seed.get('meta', {}).get('seed_version', '?')}", Colors.GREEN)

    _print("\n🔐 Encryption:", Colors.BOLD)
    issues = check_encryption(seed)
    all_issues.extend(issues)
    for lvl, msg in issues:
        _print(f"  [{lvl.upper()}] {msg}", Colors.RED if lvl == "error" else Colors.YELLOW)

    if check_hash:
        _print("\n#️⃣  Integrity:", Colors.BOLD)
        issues = check_hashes(seed)
        all_issues.extend(issues)
        for lvl, msg in issues:
            _print(f"  [{lvl.upper()}] {msg}", Colors.RED if lvl == "error" else Colors.YELLOW)
        if not issues:
            _print("  ✓ All hashes match", Colors.GREEN)

    # ── File statistics ───────────────────────────────────────────────────
    files = seed.get("files", {})
    _print(f"\n📊 Files: {len(files)} total", Colors.BLUE)
    categories: dict = {}
    for k in files:
        cat = k.split("/")[0] if "/" in k else "root"
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items()):
        _print(f"  {cat}: {count}")

    # ── Meta ──────────────────────────────────────────────────────────────
    if "meta" in seed:
        _print("\n📋 Meta:", Colors.BOLD)
        for k, v in seed["meta"].items():
            _print(f"  {k}: {v}")

    if seed.get("cron_jobs"):
        _print(f"\n⏰ Cron jobs: {len(seed['cron_jobs'])}")

    # ── Result ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    errors   = [x for x in all_issues if x[0] == "error"]
    warnings = [x for x in all_issues if x[0] == "warning"]

    if errors:
        _print(f"❌ Verification FAILED: {len(errors)} error(s)", Colors.RED)
        return False
    if warnings:
        _print(f"⚠️  Verification passed with {len(warnings)} warning(s)", Colors.YELLOW)
        return True
    _print("✅ Verification passed — no issues", Colors.GREEN)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Alice Seed verification tool")
    parser.add_argument("seed_file", help="Path to seed file (.json or .zip)")
    parser.add_argument("--check-hash", action="store_true",
                        help="Verify stored content hashes")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    ok = verify_seed_file(args.seed_file, check_hash=args.check_hash)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
