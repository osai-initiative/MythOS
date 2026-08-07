from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .constants import FLATHUB_REPOSITORY, catalog_dir
from .util import MythOSError, require_root, run


@dataclass(slots=True)
class FeatureProfile:
    key: str
    name: str
    description: str
    packages: list[str]
    flatpaks: list[str]


def load_profiles(source: Path | None = None) -> dict[str, FeatureProfile]:
    path = source or catalog_dir() / "features.json"
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MythOSError(f"Feature catalog could not be read: {exc}") from exc
    if payload.get("schema") != 1 or not isinstance(payload.get("profiles"), dict):
        raise MythOSError("Feature catalog uses an unsupported format.")
    return {
        key: FeatureProfile(key=key, **value)
        for key, value in payload["profiles"].items()
    }


def _package_installed(package: str) -> bool:
    result = run(["dpkg-query", "-W", "-f=${db:Status-Status}", package], timeout=15)
    return result.ok and result.stdout.strip() == "installed"


def _flatpak_installed(app_id: str) -> bool:
    return run(["flatpak", "info", "--system", app_id], timeout=20).ok or run(
        ["flatpak", "info", "--user", app_id], timeout=20
    ).ok


def feature_status(profile: FeatureProfile) -> dict[str, Any]:
    packages = {item: _package_installed(item) for item in profile.packages}
    flatpaks = {item: _flatpak_installed(item) for item in profile.flatpaks}
    values = list(packages.values()) + list(flatpaks.values())
    return {
        "key": profile.key,
        "name": profile.name,
        "description": profile.description,
        "installed": bool(values) and all(values),
        "partial": any(values) and not all(values),
        "packages": packages,
        "flatpaks": flatpaks,
    }


def list_features() -> list[dict[str, Any]]:
    return [feature_status(profile) for profile in load_profiles().values()]


def enable_feature(key: str) -> dict[str, Any]:
    require_root()
    profiles = load_profiles()
    if key not in profiles:
        raise MythOSError(f"Unknown optional feature: {key}")
    profile = profiles[key]
    if profile.packages:
        run(["apt-get", "update"], check=True, timeout=900)
        run(
            ["apt-get", "install", "-y", "--no-install-recommends", *profile.packages],
            check=True,
            timeout=3600,
        )
    if profile.flatpaks:
        run(
            ["flatpak", "remote-add", "--system", "--if-not-exists", "flathub", FLATHUB_REPOSITORY],
            check=True,
            timeout=180,
        )
        for app_id in profile.flatpaks:
            run(
                ["flatpak", "install", "--system", "--noninteractive", "-y", "flathub", app_id],
                check=True,
                timeout=3600,
            )
    config = Config.load()
    if key not in config.enabled_features:
        config.enabled_features.append(key)
        config.save()
    if key == "snap":
        run(["systemctl", "enable", "--now", "snapd.socket"], check=True, timeout=120)
    return feature_status(profile)


def mark_feature_disabled(key: str) -> dict[str, Any]:
    """Disable integration without deleting applications or user data."""

    require_root()
    profiles = load_profiles()
    if key not in profiles:
        raise MythOSError(f"Unknown optional feature: {key}")
    config = Config.load()
    config.enabled_features = [item for item in config.enabled_features if item != key]
    config.save()
    if key == "snap":
        run(["systemctl", "disable", "--now", "snapd.socket"], timeout=120)
    value = feature_status(profiles[key])
    value["enabled"] = False
    value["note"] = "Installed applications and their data were kept."
    return value

