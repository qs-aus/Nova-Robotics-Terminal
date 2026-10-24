"""Configuration, filesystem paths and persistent settings.

Everything Nova needs lives in one folder (``NOVA_HOME`` or ``~/.nova_robotics``)
so the console is portable and fully offline. No network access, no external
packages, no telemetry.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "NOVA ROBOTICS // SAINT CONTROL"
SHORT_NAME = "NOVA"
VERSION = "1.0.0"
TAGLINE = "Strategic Artificially Intelligent Nuclear Transport — Field Console"
RECORD_COUNT = 65

DEFAULT_ACCESS_CODE = "J5-1986"

DEFAULT_SETTINGS = {
    "operator": "FIELD OPERATOR",
    "touch_keyboard": True,
    "access_code": DEFAULT_ACCESS_CODE,
    "sim_seed": 1986,
}


def home_dir() -> Path:
    """Return the Nova data directory (overridable with NOVA_HOME)."""
    env = os.environ.get("NOVA_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".nova_robotics"


def paths() -> dict[str, Path]:
    """Return the named locations used by the console."""
    home = home_dir()
    return {
        "home": home,
        "db": home / "nova.db",
        "docs": home / "documents",
        "code": home / "code",
        "logs": home / "logs",
        "settings": home / "settings.json",
    }


def ensure_dirs() -> dict[str, Path]:
    """Create the data folders if they are missing and return the path map."""
    p = paths()
    for key in ("home", "docs", "code", "logs"):
        p[key].mkdir(parents=True, exist_ok=True)
    return p


class Settings:
    """Tiny JSON-backed settings store with safe defaults."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else paths()["settings"]
        self.data: dict = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> "Settings":
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.save()
            return self
        except (OSError, ValueError):
            return self
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key in DEFAULT_SETTINGS:
                    self.data[key] = value
        return self

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    def get(self, key: str, default=None):
        return self.data.get(key, DEFAULT_SETTINGS.get(key, default))

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    def toggle(self, key: str) -> bool:
        self.set(key, not bool(self.get(key)))
        return bool(self.get(key))


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
