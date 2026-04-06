#!/usr/bin/env python3
"""
Alice Seed Generator
Pack an AI agent's capabilities, memories, and configuration into a
single portable file for migration and disaster recovery.
"""

import sys
import os
import json
import hashlib
import zipfile
import base64
import secrets
import getpass
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from config import get_profile, get_hostname

SEED_VERSION = "2.0.0"

SENSITIVE_KEYS = {"apikey", "secret", "token", "password", "accesstoken", "privatekey"}

# ── Encryption ────────────────────────────────────────────────────────────────

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


def _derive_key(password: str, salt: bytes, iterations: int = 100_000) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_aes256_gcm(data: str, password: str) -> Tuple[str, str, str]:
    """AES-256-GCM encrypt. Returns (b64-ciphertext, b64-salt, b64-nonce)."""
    salt  = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    key   = _derive_key(password, salt)
    ciphertext = AESGCM(key).encrypt(nonce, data.encode("utf-8"), None)
    return (
        base64.b64encode(ciphertext).decode(),
        base64.b64encode(salt).decode(),
        base64.b64encode(nonce).decode(),
    )


def decrypt_aes256_gcm(enc_b64: str, salt_b64: str, nonce_b64: str, password: str) -> str:
    """AES-256-GCM decrypt."""
    salt       = base64.b64decode(salt_b64)
    nonce      = base64.b64decode(nonce_b64)
    ciphertext = base64.b64decode(enc_b64)
    key        = _derive_key(password, salt)
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")


# ── Utilities ─────────────────────────────────────────────────────────────────

def get_file_hash(filepath: Path) -> Optional[str]:
    """Return SHA-256 hex digest of *filepath*, or None if it does not exist."""
    if not filepath.exists():
        return None
    sha = hashlib.sha256()
    with open(filepath, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def get_cron_jobs() -> List[str]:
    """Return current crontab entries (empty list on Windows or if none)."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [line for line in result.stdout.splitlines() if line.strip()]
        return []
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def get_agent_version(agent: str) -> str:
    """Try to read the agent's version string."""
    try:
        if agent == "nanobot":
            import nanobot  # type: ignore
            return getattr(nanobot, "__version__", "unknown")
    except ImportError:
        pass
    return "unknown"


# ── Sanitisation ──────────────────────────────────────────────────────────────

def _is_sensitive(key: str) -> bool:
    lower = key.lower()
    return any(s in lower for s in SENSITIVE_KEYS)


def sanitize(obj: object) -> object:
    """Recursively replace sensitive string values with a placeholder."""
    if isinstance(obj, dict):
        return {
            k: (f"__SECRET_{len(str(v))}chars__" if _is_sensitive(k) and v else sanitize(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [sanitize(i) for i in obj]
    return obj


def extract_secrets(obj: object, path: str = "") -> Dict[str, str]:
    """Collect all key→value pairs whose key is sensitive."""
    found: Dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            full = f"{path}.{k}" if path else k
            if _is_sensitive(k) and v and not str(v).startswith("__SECRET_"):
                found[full] = str(v)
            else:
                found.update(extract_secrets(v, full))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.update(extract_secrets(item, f"{path}[{i}]"))
    return found


# ── Data collection ───────────────────────────────────────────────────────────

def collect_seed_data(agent: Optional[str] = None) -> dict:
    """Gather all agent files into a seed dictionary."""
    p = get_profile(agent)
    CONFIG     = p["config"]
    MEMORY_DIR = p["memory_dir"]
    SKILLS_DIR = p["skills_dir"]
    SCRIPTS_DIR= p["scripts_dir"]
    DATA_DIR   = p["data_dir"]
    agent_name = agent or "unknown"

    seed: dict = {
        "meta": {
            "seed_version":   SEED_VERSION,
            "created_at":     datetime.now().isoformat(),
            "agent_name":     agent_name,
            "agent_version":  get_agent_version(agent_name),
            "hostname":       get_hostname(),
        },
        "files":       {},
        "cron_jobs":   get_cron_jobs(),
        "file_hashes": {},
    }

    def add_file(key: str, path: Path, text: Optional[str] = None) -> None:
        try:
            content = text if text is not None else path.read_text(encoding="utf-8")
            seed["files"][key] = content
            # Hash the stored content (which may be sanitised), not the raw file bytes
            seed["file_hashes"][key] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        except (OSError, UnicodeDecodeError):
            pass  # silently skip unreadable files

    # Config (sanitised)
    if CONFIG.exists():
        try:
            raw = json.loads(CONFIG.read_text(encoding="utf-8"))
            add_file("config.json", CONFIG, json.dumps(sanitize(raw), ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            add_file("config.json", CONFIG)

    # Memory files
    for name in ("MEMORY.md", "HISTORY.md"):
        fp = MEMORY_DIR / name
        if fp.exists():
            add_file(f"memory/{name}", fp)

    # Soul / agent docs
    WORKSPACE = p["workspace"]
    for name in ("SOUL.md", "AGENTS.md"):
        fp = WORKSPACE / name
        if fp.exists():
            add_file(name, fp)

    # Skills
    if SKILLS_DIR.exists():
        for fp in SKILLS_DIR.rglob("*"):
            if fp.is_file() and not fp.name.startswith("."):
                key = "skills/" + fp.relative_to(SKILLS_DIR).as_posix()
                add_file(key, fp)

    # Scripts
    if SCRIPTS_DIR.exists():
        for fp in SCRIPTS_DIR.iterdir():
            if fp.is_file():
                add_file(f"scripts/{fp.name}", fp)

    # Extra data files
    origin_state = DATA_DIR / "origin_path_state.json"
    if origin_state.exists():
        add_file("data/origin_path_state.json", origin_state)

    return seed


# ── Package creation ──────────────────────────────────────────────────────────

def create_seed_package(
    encrypt: bool = False,
    password: Optional[str] = None,
    agent: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """
    Create JSON + ZIP seed packages.

    Returns (json_path, zip_path, encrypted_zip_path).
    encrypted_zip_path is None when encryption is skipped.
    """
    print("🌱 Generating Alice Seed…")

    p = get_profile(agent)
    out = output_dir or p["output_dir"]
    out.mkdir(parents=True, exist_ok=True)

    # ── Password prompt ────────────────────────────────────────────────────
    if encrypt:
        if not CRYPTO_AVAILABLE:
            print("⚠️  cryptography library not installed — skipping encryption.")
            encrypt = False
        else:
            if not password:
                password = getpass.getpass("🔐 Encryption password: ")
                if not password:
                    print("⚠️  No password entered — skipping encryption.")
                    encrypt = False
                else:
                    confirm = getpass.getpass("🔐 Confirm password: ")
                    if password != confirm:
                        print("❌ Passwords do not match.")
                        return None, None, None

    seed = collect_seed_data(agent)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Plain JSON ─────────────────────────────────────────────────────────
    json_path = out / f"alice_seed_{timestamp}.json"
    json_path.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Plain ZIP ──────────────────────────────────────────────────────────
    zip_path = out / f"alice_seed_{timestamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("seed.json", json.dumps(seed, ensure_ascii=False, indent=2))

    encrypted_zip_path: Optional[Path] = None

    # ── Encrypted ZIP ──────────────────────────────────────────────────────
    if encrypt and password:
        try:
            config_raw: dict = {}
            if "config.json" in seed["files"]:
                config_raw = json.loads(
                    (p["config"]).read_text(encoding="utf-8")
                    if p["config"].exists()
                    else "{}"
                )

            secrets_dict = extract_secrets(config_raw)
            encrypted_payload: dict = {}
            if secrets_dict:
                enc, salt, nonce = encrypt_aes256_gcm(
                    json.dumps(secrets_dict), password
                )
                encrypted_payload = {"secrets": enc, "salt": salt, "nonce": nonce}

            encrypted_seed = {
                "header": {
                    "version":    SEED_VERSION,
                    "algo":       "AES-256-GCM",
                    "kdf_iters":  100_000,
                    "created":    datetime.now().isoformat(),
                    "agent_name": seed["meta"]["agent_name"],
                },
                "encrypted": encrypted_payload,
                "public": seed,
            }

            encrypted_zip_path = out / f"alice_seed_{timestamp}_encrypted.zip"
            with zipfile.ZipFile(encrypted_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(
                    "seed.json",
                    json.dumps(encrypted_seed, ensure_ascii=False, indent=2),
                )
            print(f"🔐 Encrypted seed: {encrypted_zip_path.name}")
        except Exception as exc:
            print(f"⚠️  Encryption failed: {exc}")
            encrypted_zip_path = None

    # ── Summary ────────────────────────────────────────────────────────────
    files = seed["files"]
    print(
        f"\n✅ Seed generated\n"
        f"   Version  : {seed['meta']['seed_version']}\n"
        f"   Agent    : {seed['meta']['agent_name']} @ {seed['meta']['hostname']}\n"
        f"   Encrypted: {'yes' if encrypted_zip_path else 'no'}\n"
        f"   Files    : {len(files)} total\n"
        f"     config : {sum(1 for k in files if k == 'config.json')}\n"
        f"     memory : {sum(1 for k in files if k.startswith('memory/'))}\n"
        f"     skills : {sum(1 for k in files if k.startswith('skills/'))}\n"
        f"     scripts: {sum(1 for k in files if k.startswith('scripts/'))}\n"
        f"   JSON     : {json_path.name}\n"
        f"   ZIP      : {zip_path.name}"
    )
    if seed["cron_jobs"]:
        print(f"   Cron jobs: {len(seed['cron_jobs'])}")

    return json_path, zip_path, encrypted_zip_path


if __name__ == "__main__":
    create_seed_package()
