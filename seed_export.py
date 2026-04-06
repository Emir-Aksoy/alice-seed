#!/usr/bin/env python3
"""
Alice Seed Export
Convert a seed file to various AI framework formats:
  langchain, autogen, crewai, openai, claude
"""

import sys
import json
import zipfile
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


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

def _load_seed(seed_file: str) -> Optional[dict]:
    try:
        if seed_file.endswith(".zip"):
            with zipfile.ZipFile(seed_file, "r") as zf:
                names  = zf.namelist()
                target = "seed.json" if "seed.json" in names else next(
                    (n for n in names if n.endswith(".json")), None
                )
                if target is None:
                    return None
                return json.loads(zf.read(target))
        else:
            return json.loads(Path(seed_file).read_text(encoding="utf-8"))
    except Exception as exc:
        _print(f"❌ Cannot read seed: {exc}", Colors.RED)
        return None


def _get_memory(seed: dict, limit: Optional[int] = None) -> str:
    for k, v in seed.get("files", {}).items():
        if "MEMORY.md" in k:
            return v[:limit] if limit else v
    return ""


def _get_config(seed: dict) -> dict:
    raw = seed.get("files", {}).get("config.json", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _base_header(fmt: str) -> dict:
    return {
        "version":     "1.0",
        "exported_at": datetime.now().isoformat(),
        "source":      "alice_seed",
        "format":      fmt,
    }


# ── Exporters ─────────────────────────────────────────────────────────────────

def _to_langchain(seed: dict) -> dict:
    cfg = _get_config(seed)
    out = _base_header("langchain")
    out["config"] = {
        "model":       cfg.get("model", "gpt-4"),
        "temperature": cfg.get("temperature", 0.7),
        "max_tokens":  cfg.get("maxTokens", 4096),
    }
    out["memory"] = {"system_prompt": _get_memory(seed)}
    out["tools"]  = [
        {
            "name": "web_search",
            "description": "Search the web for information",
            "args_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        {
            "name": "web_fetch",
            "description": "Fetch URL content",
            "args_schema": {
                "type": "object",
                "properties": {
                    "url":      {"type": "string"},
                    "maxChars": {"type": "integer"},
                },
                "required": ["url"],
            },
        },
    ]
    return out


def _to_autogen(seed: dict) -> dict:
    cfg = _get_config(seed)
    out = _base_header("autogen")
    llm = {
        "model":       cfg.get("model", "gpt-4"),
        "temperature": cfg.get("temperature", 0.7),
        "max_tokens":  cfg.get("maxTokens", 4096),
    }
    out["llm_config"] = llm
    out["agents"] = [
        {
            "name":           "alice",
            "system_message": _get_memory(seed, limit=8000),
            "llm_config":     llm,
            "function_map":   {},
        }
    ]
    return out


def _to_crewai(seed: dict) -> dict:
    out = _base_header("crewai")
    out["agents"] = [
        {
            "role":               "AI Assistant",
            "goal":               "Help user with tasks",
            "backstory":          _get_memory(seed, limit=4000),
            "verbose":            True,
            "allow_delegation":   False,
        }
    ]
    out["tools"] = [
        {"name": "web_search", "description": "Search the web"},
        {"name": "web_fetch",  "description": "Fetch URL content"},
    ]
    return out


def _to_openai(seed: dict) -> dict:
    cfg = _get_config(seed)
    out = _base_header("openai")
    out["model"]        = cfg.get("model", "gpt-4")
    out["temperature"]  = cfg.get("temperature", 0.7)
    out["max_tokens"]   = cfg.get("maxTokens", 4096)
    out["instructions"] = _get_memory(seed, limit=32_000)
    out["tools"] = [
        {
            "type": "function",
            "function": {
                "name":        "web_search",
                "description": "Search the web for information",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]
    return out


def _to_claude(seed: dict) -> dict:
    """
    Export to Claude Code / Anthropic SDK format.
    Produces a settings.json-compatible structure plus memory files.
    """
    cfg = _get_config(seed)
    out = _base_header("claude")

    # Claude Code settings structure
    out["settings"] = {
        "model":               cfg.get("model", "claude-sonnet-4-6"),
        "temperature":         cfg.get("temperature", 1.0),
        "maxTokens":           cfg.get("maxTokens", 8096),
        "customApiKeyHelper":  cfg.get("customApiKeyHelper", ""),
        "env":                 {},
    }

    # Extract MEMORY.md as the system prompt source
    memory_files: dict = {}
    for k, v in seed.get("files", {}).items():
        if k.startswith("memory/"):
            memory_files[k] = v

    out["memory_files"] = memory_files

    # CLAUDE.md content derived from MEMORY.md
    main_memory = _get_memory(seed)
    if main_memory:
        out["CLAUDE_md"] = f"# Agent Memory\n\n{main_memory}"

    # Tool hooks (placeholder — adapt to your actual Claude hooks config)
    out["hooks"] = {}

    # Skills → custom slash commands
    skills: dict = {}
    for k, v in seed.get("files", {}).items():
        if k.startswith("skills/"):
            skills[k] = v
    out["skills"] = skills

    return out


# ── Main export function ──────────────────────────────────────────────────────

FORMATS = {
    "langchain": _to_langchain,
    "autogen":   _to_autogen,
    "crewai":    _to_crewai,
    "openai":    _to_openai,
    "claude":    _to_claude,
}


def export_seed(
    seed_file: str,
    target_format: str,
    output_dir: Optional[str] = None,
) -> bool:
    _print(f"\n📤 Exporting seed as '{target_format}'…", Colors.BOLD)
    print("=" * 60)

    seed = _load_seed(seed_file)
    if seed is None:
        return False

    # For encrypted seeds, work on the public portion
    if "public" in seed and "header" in seed:
        seed = seed["public"]

    if target_format not in FORMATS:
        _print(f"❌ Unknown format: '{target_format}'", Colors.RED)
        _print(f"   Available: {', '.join(FORMATS)}", Colors.YELLOW)
        return False

    output = FORMATS[target_format](seed)

    out_dir = Path(output_dir) if output_dir else Path(seed_file).parent
    if not out_dir.exists():
        _print(f"❌ Output directory does not exist: {out_dir}", Colors.RED)
        return False

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"alice_export_{target_format}_{stamp}.json"

    out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    _print(f"✅ Exported: {out_file}", Colors.GREEN)
    _print(f"   Size: {out_file.stat().st_size / 1024:.2f} KB", Colors.BLUE)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Alice Seed export tool")
    parser.add_argument("seed_file", help="Path to seed file (.json or .zip)")
    parser.add_argument("--format", "-f", required=True, choices=list(FORMATS),
                        help="Target framework format")
    parser.add_argument("--output", "-o", default=None, help="Output directory")
    args = parser.parse_args()

    ok = export_seed(args.seed_file, args.format, args.output)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
