"""Authenticated MythOS release discovery for stable and rolling tracks."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .constants import RELEASE_CACHE_DIR, RELEASE_DISCOVERY_BASE, RELEASE_KEYRING, rooted
from .util import MythOSError, require_root


CHANNELS = {"stable", "rolling"}
GITHUB_RELEASE_PREFIX = "https://github.com/osai-initiative/MythOS/releases/download/"
MAX_DOCUMENT_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    channel: str
    package_url: str
    package_sha256: str
    architecture: str


def set_channel(channel: str) -> dict[str, str]:
    require_root()
    if channel not in CHANNELS:
        raise MythOSError("Release channel must be stable or rolling.")
    config = Config.load()
    config.release_channel = channel
    config.save()
    return {"release_channel": channel}


def _download(url: str, *, limit: int = MAX_DOCUMENT_BYTES) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "MythOS-release-updater/1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise MythOSError(f"Release server returned HTTP {response.status}.")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > limit:
                raise MythOSError("Release metadata is unexpectedly large.")
            value = response.read(limit + 1)
    except (OSError, ValueError) as exc:
        raise MythOSError(f"Could not download release metadata: {exc}") from exc
    if len(value) > limit:
        raise MythOSError("Release metadata is unexpectedly large.")
    return value


def _json(value: bytes, label: str) -> dict[str, Any]:
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise MythOSError(f"{label} is not valid JSON.") from exc
    if not isinstance(result, dict):
        raise MythOSError(f"{label} has an invalid shape.")
    return result


def _release_url(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(GITHUB_RELEASE_PREFIX):
        raise MythOSError("Release metadata points outside the official MythOS GitHub releases.")
    return value


def _verify(manifest: bytes, signature: bytes, keyring: Path | None = None) -> None:
    trusted_keyring = keyring or rooted(RELEASE_KEYRING)
    if not trusted_keyring.is_file():
        raise MythOSError("The installed MythOS release signing key is unavailable.")
    with tempfile.TemporaryDirectory(prefix="mythos-release-") as directory:
        root = Path(directory)
        manifest_path, signature_path = root / "release.json", root / "release.json.asc"
        manifest_path.write_bytes(manifest)
        signature_path.write_bytes(signature)
        result = subprocess.run(
            ["gpgv", "--keyring", str(trusted_keyring), str(signature_path), str(manifest_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    if result.returncode != 0:
        raise MythOSError("The MythOS release signature could not be verified.")


def check(channel: str | None = None) -> Release:
    selected = channel or Config.load().release_channel
    if selected not in CHANNELS:
        raise MythOSError("The configured MythOS release channel is invalid.")
    discovery = _json(_download(f"{RELEASE_DISCOVERY_BASE}/{selected}.json"), "Release discovery")
    if discovery.get("schema") != 1 or discovery.get("product") != "MythOS" or discovery.get("channel") != selected:
        raise MythOSError("Release discovery did not describe the selected MythOS channel.")
    manifest_url = _release_url(discovery.get("manifest_url"))
    signature_url = _release_url(discovery.get("signature_url"))
    if signature_url != f"{manifest_url}.asc":
        raise MythOSError("Release discovery has an unexpected signature location.")
    manifest = _download(manifest_url)
    _verify(manifest, _download(signature_url))
    value = _json(manifest, "Signed release manifest")
    artifacts = value.get("artifacts")
    if value.get("schema") != 1 or value.get("product") != "MythOS" or value.get("channel") != selected or not isinstance(artifacts, list):
        raise MythOSError("Signed release manifest has an invalid shape.")
    machine = os.uname().machine
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("kind") != "deb" or artifact.get("architecture") != machine:
            continue
        package_url = _release_url(artifact.get("url"))
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            continue
        version = value.get("version")
        if isinstance(version, str) and version:
            return Release(version, selected, package_url, digest, machine)
    raise MythOSError(f"No signed MythOS package is available for {machine}.")


def verify_package(path: Path, release: Release) -> None:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    if digest != release.package_sha256:
        raise MythOSError("Downloaded MythOS package checksum did not match the signed manifest.")


def stage() -> dict[str, Any]:
    """Download a signed release and hand it to the existing offline updater."""

    require_root()
    release = check()
    name = release.package_url.rsplit("/", 1)[-1]
    if not name.startswith("mythos-core_") or not name.endswith("_all.deb") or "/" in name:
        raise MythOSError("Signed release package name is invalid.")
    destination = rooted(RELEASE_CACHE_DIR) / release.version / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".partial")
    request = urllib.request.Request(release.package_url, headers={"User-Agent": "MythOS-release-updater/1"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            if response.status != 200:
                raise MythOSError(f"Release server returned HTTP {response.status}.")
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except OSError as exc:
        raise MythOSError(f"Could not download the signed MythOS package: {exc}") from exc
    try:
        verify_package(temporary, release)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(destination)
    from .updates import stage_release_package

    return stage_release_package(destination, release.version, release.channel)
