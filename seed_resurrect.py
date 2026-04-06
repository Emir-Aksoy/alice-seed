#!/usr/bin/env python3
"""
Alice Seed Resurrect
Restore an AI agent from a seed file.
Supports decryption, dry-run preview, selective component recovery,
and automatic backup before overwriting existing files.
"""

import sys
import json
import zipfile
import argparse
import getpass
import hashlib
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from config import get_profile


class Colors:
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"


def _print(text: str, color: str = Colors.RESET) -> None:
    print(f"{color}{text}{Colors.RESET}")


# ── Decryption ────────────────────────────────────────────────────────────────

def _decrypt_secrets(enc_block: dict, password: str) -> Dict[str, str]:
    """Decrypt the secrets block using AES-256-GCM."""
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt       = base64.b64decode(enc_block["salt"])
    nonce      = base64.b64decode(enc_block["nonce"])
    ciphertext = base64.b64decode(enc_block["secrets"])
    iters      = enc_block.get("kdf_iters", 100_000)  # backward-compatible

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters)
    key = kdf.derive(password.encode("utf-8"))

    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))


# ── Backup ────────────────────────────────────────────────────────────────────

def _backup_current(profile: dict) -> Path:
    backup_dir = profile["backup_dir"]
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest      = backup_dir / f"pre_restore_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)

    candidates = [
        (profile["config"],             "config.json"),
        (profile["memory_dir"] / "MEMORY.md",  "memory/MEMORY.md"),
        (profile["memory_dir"] / "HISTORY.md", "memory/HISTORY.md"),
    ]
    for src, rel in candidates:
        if src.exists():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
            _print(f"  ✓ Backed up: {rel}", Colors.GREEN)

    _print(f"  📁 Backup location: {dest}", Colors.BLUE)
    return dest


# ── Secret injection ──────────────────────────────────────────────────────────

def _apply_secrets(config: dict, secrets: Dict[str, str]) -> dict:
    """
    Re-inject decrypted secrets into *config* using exact key paths.
    Path format: 'parent.child' or 'parent[0].child'.
    Falls back to an exact top-level key match only — no fuzzy matching.
    """
    for path, value in secrets.items():
        parts = path.lstrip(".").split(".")
        obj   = config
        try:
            for part in parts[:-1]:
                if "[" in part:
                    name, idx = part.rstrip("]").split("[")
                    obj = obj[name][int(idx)]
                else:
                    obj = obj[part]
            last = parts[-1]
            if "[" in last:
                name, idx = last.rstrip("]").split("[")
                obj[name][int(idx)] = value
            else:
                if last in obj:
                    obj[last] = value
        except (KeyError, IndexError, TypeError):
            pass  # path no longer exists in this config — skip silently
    return config


# ── File restoration ──────────────────────────────────────────────────────────

def _resolve_target(filepath: str, profile: dict) -> Path:
    """Map a seed-relative path to an absolute filesystem path."""
    if filepath.startswith("memory/"):
        return profile["memory_dir"] / filepath[len("memory/"):]
    if filepath.startswith("skills/"):
        return profile["skills_dir"] / filepath[len("skills/"):]
    if filepath.startswith("scripts/"):
        return profile["scripts_dir"] / filepath[len("scripts/"):]
    if filepath.startswith("data/"):
        return profile["data_dir"] / filepath[len("data/"):]
    return profile["workspace"] / filepath


def restore_files(
    seed: dict,
    profile: dict,
    secrets: Optional[Dict[str, str]] = None,
    dry_run: bool = False,
) -> Tuple[int, int]:
    ok = fail = 0
    stored_hashes = seed.get("file_hashes", {})

    for filepath, content in seed.get("files", {}).items():
        target = _resolve_target(filepath, profile)
        try:
            # Inject secrets into config
            if filepath == "config.json" and secrets:
                config = json.loads(content)
                config  = _apply_secrets(config, secrets)
                content = json.dumps(config, ensure_ascii=False, indent=2)

            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

                # Verify written hash against stored hash
                stored = stored_hashes.get(filepath)
                if stored:
                    written_hash = hashlib.sha256(
                        target.read_bytes()
                    ).hexdigest()
                    if written_hash != stored:
                        _print(f"  ⚠ Hash mismatch after write: {filepath}", Colors.YELLOW)

            _print(f"  {'(dry)' if dry_run else '✓'} {filepath}", Colors.GREEN)
            ok += 1
        except Exception as exc:
            _print(f"  ✗ {filepath} — {exc}", Colors.RED)
            fail += 1

    return ok, fail


# ── Cron jobs ─────────────────────────────────────────────────────────────────

def _show_cron_jobs(jobs: List[str]) -> None:
    if not jobs:
        _print("  ⏰ No cron jobs in seed", Colors.BLUE)
        return
    _print(f"\n⏰ Cron jobs ({len(jobs)}):", Colors.BOLD)
    for job in jobs:
        _print(f"  {job}", Colors.YELLOW)
    _print("\n💡 To restore cron jobs manually:", Colors.YELLOW)
    _print("    crontab -e  # then add the entries above", Colors.BLUE)


# ── Post-restore verification ─────────────────────────────────────────────────

def _verify_restore(seed: dict, profile: dict) -> bool:
    _print("\n🔍 Verifying restore…", Colors.BOLD)
    stored_hashes = seed.get("file_hashes", {})
    all_ok = True

    for filepath in seed.get("files", {}):
        target = _resolve_target(filepath, profile)
        if not target.exists():
            _print(f"  ✗ Missing: {filepath}", Colors.RED)
            all_ok = False
            continue

        stored = stored_hashes.get(filepath)
        if stored:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual == stored:
                _print(f"  ✓ {filepath}", Colors.GREEN)
            else:
                _print(f"  ⚠ Hash mismatch: {filepath}", Colors.YELLOW)
                all_ok = False
        else:
            _print(f"  ✓ {filepath} (no hash to verify)", Colors.GREEN)

    return all_ok


# ── Main ──────────────────────────────────────────────────────────────────────

def resurrect_seed(
    seed_file: str,
    decrypt: bool = False,
    password: Optional[str] = None,
    dry_run: bool = False,
    components: str = "all",
    agent: Optional[str] = None,
) -> bool:
    _print("\n🌱 Resurrecting AI from seed…", Colors.BOLD)
    print("=" * 60)

    profile = get_profile(agent)

    # ── Load seed ─────────────────────────────────────────────────────────
    try:
        if seed_file.endswith(".zip"):
            with zipfile.ZipFile(seed_file, "r") as zf:
                names  = zf.namelist()
                target = "seed.json" if "seed.json" in names else next(
                    (n for n in names if n.endswith(".json")), None
                )
                if target is None:
                    _print("❌ No JSON file found inside ZIP", Colors.RED)
                    return False
                seed = json.loads(zf.read(target))
        else:
            seed = json.loads(Path(seed_file).read_text(encoding="utf-8"))
    except Exception as exc:
        _print(f"❌ Cannot read seed file: {exc}", Colors.RED)
        return False

    # For encrypted seeds the real data is under 'public'
    if "public" in seed and "header" in seed:
        enc_block = seed.get("encrypted", {})
        seed      = seed["public"]
        seed["_enc_block"] = enc_block  # carry along for decryption step
    else:
        enc_block = {}

    # ── Show meta ─────────────────────────────────────────────────────────
    if "meta" in seed:
        m = seed["meta"]
        _print("\n📋 Seed info:", Colors.BOLD)
        _print(f"  Version: {m.get('seed_version', '?')}")
        _print(f"  Created: {m.get('created_at', '?')}")
        _print(f"  Agent  : {m.get('agent_name', '?')} @ {m.get('hostname', '?')}")

    # ── Decrypt secrets ───────────────────────────────────────────────────
    secrets: Dict[str, str] = {}
    actual_enc_block = seed.pop("_enc_block", enc_block)
    if decrypt:
        if actual_enc_block and actual_enc_block.get("secrets"):
            if not password:
                password = getpass.getpass("🔐 Decryption password: ")
            try:
                secrets = _decrypt_secrets(actual_enc_block, password)
                _print(f"  ✓ Decrypted {len(secrets)} secret(s)", Colors.GREEN)
            except Exception as exc:
                _print(f"  ✗ Decryption failed: {exc}", Colors.RED)
                return False
        else:
            _print("  ⚠ No encrypted block found — nothing to decrypt", Colors.YELLOW)

    # ── Backup ────────────────────────────────────────────────────────────
    if not dry_run:
        _backup_current(profile)

    # ── Restore ───────────────────────────────────────────────────────────
    restore_list = ["files", "cron"] if components == "all" else components.split(",")

    if "files" in restore_list:
        _print("\n📂 Restoring files…", Colors.BOLD)
        ok, fail = restore_files(seed, profile, secrets, dry_run)
        _print(
            f"  Done: {ok} ok, {fail} failed",
            Colors.GREEN if fail == 0 else Colors.YELLOW,
        )

    if "cron" in restore_list:
        _show_cron_jobs(seed.get("cron_jobs", []))

    # ── Verify ────────────────────────────────────────────────────────────
    if not dry_run:
        _verify_restore(seed, profile)

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if dry_run:
        _print("✅ Dry-run complete — no files were written", Colors.BLUE)
    else:
        _print("✅ Resurrection complete!", Colors.GREEN)
        _print("💡 Cron jobs must be restored manually (see above)", Colors.YELLOW)
        _print("💡 Rollback backup is in the backup/ directory", Colors.YELLOW)

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Alice Seed resurrection tool")
    parser.add_argument("seed_file", help="Path to seed file (.json or .zip)")
    parser.add_argument("--decrypt", "-d", action="store_true",
                        help="Decrypt secrets from encrypted seed")
    parser.add_argument("--password", "-p", default=None,
                        help="Decryption password (prompted if omitted)")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Preview what would be restored without writing")
    parser.add_argument("--components", "-c", default="all",
                        help="Comma-separated components: files,cron  (default: all)")
    parser.add_argument("--agent", "-a", default=None,
                        choices=["nanobot", "claude"],
                        help="Target agent profile (auto-detected if omitted)")
    args = parser.parse_args()

    ok = resurrect_seed(
        args.seed_file,
        decrypt=args.decrypt,
        password=args.password,
        dry_run=args.dry_run,
        components=args.components,
        agent=args.agent,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
