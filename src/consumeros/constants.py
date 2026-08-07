from __future__ import annotations

import os
from pathlib import Path


APP_ID = "org.consumeros.SystemHub"
VERSION = "1.0.0"
DEFAULT_COMPATIBILITY_FEED = "https://updates.consumeros.invalid/v1/compatibility.json"
FLATHUB_REPOSITORY = "https://flathub.org/repo/flathub.flatpakrepo"


def system_root() -> Path:
    """Return the filesystem root, replaceable for tests and image assembly."""

    return Path(os.environ.get("CONSUMEROS_ROOT", "/")).resolve()


def rooted(path: str | Path) -> Path:
    value = Path(path)
    if not value.is_absolute():
        raise ValueError(f"system path must be absolute: {path}")
    return system_root() / value.relative_to("/")


def catalog_dir() -> Path:
    override = os.environ.get("CONSUMEROS_CATALOG_DIR")
    if override:
        return Path(override)
    installed = rooted("/usr/share/consumeros/catalog")
    if installed.exists():
        return installed
    return Path(__file__).resolve().parents[2] / "data" / "catalog"


STATE_DIR = "/var/lib/consumeros"
CONFIG_FILE = "/etc/consumeros/config.toml"
UPDATE_STATE = f"{STATE_DIR}/update.json"
UPDATE_HISTORY = f"{STATE_DIR}/update-history.json"
ROLLBACK_REQUEST = f"{STATE_DIR}/rollback-request"
ROLLBACK_COMPLETE = f"{STATE_DIR}/rollback-complete"
SYSTEM_UPDATE_LINK = "/system-update"
SYSTEM_UPDATE_TARGET = f"{STATE_DIR}/offline-update"
