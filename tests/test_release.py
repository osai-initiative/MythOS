import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mythos.config import Config
from mythos.release import Release, _download, _verify, check, set_channel, stage, verify_package
from mythos.util import MythOSError


def test_signed_release_discovery_uses_only_official_github_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_url = "https://github.com/osai-initiative/MythOS/releases/download/v1.0.1/mythos-release.json"
    package_url = "https://github.com/osai-initiative/MythOS/releases/download/v1.0.1/mythos-core_1.0.1_all.deb"
    manifest = {
        "schema": 1,
        "product": "MythOS",
        "channel": "rolling",
        "version": "1.0.1",
        "artifacts": [{"kind": "deb", "architecture": "x86_64", "url": package_url, "sha256": "a" * 64}],
    }
    payloads = {
        "https://osaii.wyvernhub.net/mythos/updates/rolling.json": json.dumps(
            {"schema": 1, "product": "MythOS", "channel": "rolling", "manifest_url": manifest_url, "signature_url": f"{manifest_url}.asc"}
        ).encode(),
        manifest_url: json.dumps(manifest).encode(),
        f"{manifest_url}.asc": b"signature",
    }
    monkeypatch.setattr("mythos.release.Config.load", lambda: Config(release_channel="rolling"))
    monkeypatch.setattr("mythos.release._download", lambda url: payloads[url])
    monkeypatch.setattr("mythos.release._verify", lambda manifest, signature: None)
    monkeypatch.setattr("mythos.release.os.uname", lambda: SimpleNamespace(machine="x86_64"))
    release = check()
    assert release.version == "1.0.1"
    assert release.package_url == package_url


def test_release_rejects_untrusted_download_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mythos.release.Config.load", lambda: Config())
    monkeypatch.setattr(
        "mythos.release._download",
        lambda _url: b'{"schema":1,"product":"MythOS","channel":"stable","manifest_url":"https://example.com/release.json","signature_url":"https://example.com/release.json.asc"}',
    )
    with pytest.raises(MythOSError, match="official MythOS GitHub"):
        check()


def test_release_rejects_signature_url_not_adjacent_to_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_url = "https://github.com/osai-initiative/MythOS/releases/download/v1.0.1/mythos-release.json"
    discovery = {
        "schema": 1,
        "product": "MythOS",
        "channel": "stable",
        "manifest_url": manifest_url,
        "signature_url": "https://github.com/osai-initiative/MythOS/releases/download/v1.0.1/other.asc",
    }
    monkeypatch.setattr("mythos.release.Config.load", lambda: Config())
    monkeypatch.setattr("mythos.release._download", lambda _url: json.dumps(discovery).encode())
    with pytest.raises(MythOSError, match="unexpected signature location"):
        check()


def test_release_rejects_manifest_without_local_architecture(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_url = "https://github.com/osai-initiative/MythOS/releases/download/v1.0.1/mythos-release.json"
    package_url = "https://github.com/osai-initiative/MythOS/releases/download/v1.0.1/mythos-core_1.0.1_all.deb"
    payloads = {
        "https://osaii.wyvernhub.net/mythos/updates/stable.json": json.dumps(
            {"schema": 1, "product": "MythOS", "channel": "stable", "manifest_url": manifest_url, "signature_url": f"{manifest_url}.asc"}
        ).encode(),
        manifest_url: json.dumps(
            {"schema": 1, "product": "MythOS", "channel": "stable", "version": "1.0.1", "artifacts": [{"kind": "deb", "architecture": "arm64", "url": package_url, "sha256": "a" * 64}]}
        ).encode(),
        f"{manifest_url}.asc": b"signature",
    }
    monkeypatch.setattr("mythos.release.Config.load", lambda: Config())
    monkeypatch.setattr("mythos.release._download", lambda url: payloads[url])
    monkeypatch.setattr("mythos.release._verify", lambda manifest, signature: None)
    monkeypatch.setattr("mythos.release.os.uname", lambda: SimpleNamespace(machine="x86_64"))
    with pytest.raises(MythOSError, match="No signed MythOS package"):
        check()


def test_verify_fails_closed_when_gpgv_rejects_signature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    keyring = tmp_path / "release.gpg"
    keyring.write_bytes(b"key")
    monkeypatch.setattr(
        "mythos.release.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="bad signature"),
    )
    with pytest.raises(MythOSError, match="could not be verified"):
        _verify(b"{}", b"not-a-signature", keyring)


def test_verify_requires_installed_keyring(tmp_path: Path) -> None:
    with pytest.raises(MythOSError, match="signing key"):
        _verify(b"{}", b"signature", tmp_path / "missing.gpg")


def test_metadata_download_rejects_oversized_content_length(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200
        headers = {"Content-Length": "1000001"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _amount: int) -> bytes:
            pytest.fail("oversized metadata must not be read")

    monkeypatch.setattr("mythos.release.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(MythOSError, match="unexpectedly large"):
        _download("https://osaii.wyvernhub.net/mythos/updates/stable.json")


def test_tampered_download_is_not_staged_or_left_in_release_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _amount: int) -> bytes:
            if getattr(self, "served", False):
                return b""
            self.served = True
            return b"tampered package"

    release = Release(
        "1.0.1",
        "stable",
        "https://github.com/osai-initiative/MythOS/releases/download/v1.0.1/mythos-core_1.0.1_all.deb",
        "0" * 64,
        "x86_64",
    )
    monkeypatch.setenv("MYTHOS_ROOT", str(tmp_path))
    monkeypatch.setattr("mythos.release.require_root", lambda: None)
    monkeypatch.setattr("mythos.release.check", lambda: release)
    monkeypatch.setattr("mythos.release.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr("mythos.updates.stage_release_package", lambda *_args, **_kwargs: pytest.fail("tampered package must not stage"))

    with pytest.raises(MythOSError, match="checksum"):
        stage()
    cache = tmp_path / "var/cache/mythos/releases/1.0.1"
    assert not list(cache.glob("*"))


def test_downloaded_package_must_match_signed_hash(tmp_path: Path) -> None:
    package = tmp_path / "mythos-core.deb"
    package.write_bytes(b"package")
    release = Release("1.0.1", "stable", "https://github.com/osai-initiative/MythOS/releases/download/v1.0.1/mythos-core.deb", hashlib.sha256(b"package").hexdigest(), "x86_64")
    verify_package(package, release)
    package.write_bytes(b"tampered")
    with pytest.raises(MythOSError, match="checksum"):
        verify_package(package, release)


def test_release_channel_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mythos.release.require_root", lambda: None)
    with pytest.raises(MythOSError, match="stable or rolling"):
        set_channel("preview")
