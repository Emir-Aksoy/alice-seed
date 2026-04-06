#!/usr/bin/env python3
"""
Agent profile configuration.
Supports nanobot and claude (openclaw) agent paths.
"""

import platform
from pathlib import Path
from typing import Dict, Optional

PROFILES: Dict[str, Dict[str, Path]] = {
    "nanobot": {
        "workspace":  Path.home() / ".nanobot" / "workspace",
        "config":     Path.home() / ".nanobot" / "config.json",
        "memory_dir": Path.home() / ".nanobot" / "workspace" / "memory",
        "skills_dir": Path.home() / ".nanobot" / "workspace" / "skills",
        "scripts_dir":Path.home() / ".nanobot" / "workspace" / "scripts",
        "data_dir":   Path.home() / ".nanobot" / "workspace" / "data",
        "output_dir": Path.home() / ".nanobot" / "workspace" / "data",
        "backup_dir": Path.home() / ".nanobot" / "workspace" / "backup",
    },
    "claude": {
        "workspace":  Path.home() / ".claude",
        "config":     Path.home() / ".claude" / "settings.json",
        "memory_dir": Path.home() / ".claude" / "projects",
        "skills_dir": Path.home() / ".claude" / "skills",
        "scripts_dir":Path.home() / ".claude" / "scripts",
        "data_dir":   Path.home() / ".claude" / "data",
        "output_dir": Path.home() / ".claude" / "data",
        "backup_dir": Path.home() / ".claude" / "backup",
    },
}

_active: Optional[str] = None


def detect_agent() -> str:
    """Auto-detect which agent is installed on this machine."""
    if (Path.home() / ".nanobot").exists():
        return "nanobot"
    if (Path.home() / ".claude").exists():
        return "claude"
    return "nanobot"


def get_profile(name: Optional[str] = None) -> Dict[str, Path]:
    """Return the active agent profile, optionally switching to *name*."""
    global _active
    if name is not None:
        if name not in PROFILES:
            raise ValueError(
                f"Unknown agent: '{name}'. Available: {list(PROFILES)}"
            )
        _active = name
    elif _active is None:
        _active = detect_agent()
    return PROFILES[_active]


def active_agent() -> str:
    """Return the name of the currently active agent profile."""
    global _active
    if _active is None:
        _active = detect_agent()
    return _active


def get_hostname() -> str:
    return platform.node() or "unknown"
