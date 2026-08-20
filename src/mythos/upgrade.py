"""Idempotent state migrations for in-place MythOS releases."""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .constants import STATE_DIR, rooted
from .util import MythOSError, file_lock, read_json, require_root, write_json


SCHEMA_VERSION = 1
UPGRADE_STATE = f"{STATE_DIR}/upgrade.json"
UPGRADE_LOCK = f"{STATE_DIR}/upgrade.lock"


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _migration_1() -> list[str]:
    state_dir = rooted(STATE_DIR)
    changes: list[str] = []
    for old_name, new_name in (("update-state.json", "update.json"), ("updates.json", "update-history.json")):
        old, new = state_dir / old_name, state_dir / new_name
        if old.exists() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
            changes.append(f"moved {old_name} to {new_name}")
    return changes


MIGRATIONS: dict[int, Callable[[], list[str]]] = {1: _migration_1}


def status() -> dict[str, Any]:
    value = read_json(rooted(UPGRADE_STATE), {})
    return value if isinstance(value, dict) else {}


def migrate() -> dict[str, Any]:
    require_root()
    rooted(STATE_DIR).mkdir(parents=True, exist_ok=True)
    with file_lock(rooted(UPGRADE_LOCK)):
        previous = status()
        try:
            completed = int(previous.get("schema_version", 0))
        except (TypeError, ValueError):
            completed = 0
        if completed < 0 or completed > SCHEMA_VERSION:
            raise MythOSError("The MythOS upgrade state has an unsupported schema version.")
        applied: list[int] = []
        changes: list[str] = []
        for version in range(completed + 1, SCHEMA_VERSION + 1):
            changes.extend(MIGRATIONS[version]())
            applied.append(version)
        result = {"schema_version": SCHEMA_VERSION, "updated_at": _now(), "applied": applied, "changes": changes}
        write_json(rooted(UPGRADE_STATE), result, mode=0o600)
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m mythos.upgrade")
    parser.add_argument("--post-install", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    if args.status:
        print(status())
        return 0
    if not args.post_install:
        parser.error("choose --post-install or --status")
    migrate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
