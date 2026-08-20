import os
from pathlib import Path

import pytest

from mythos.constants import ROLLBACK_COMPLETE, ROLLBACK_REQUEST, SYSTEM_UPDATE_LINK, SYSTEM_UPDATE_TARGET
from mythos.models import CommandResult
from mythos.updates import (
    _system_update_requested,
    apply_offline_update,
    bless_boot,
    consumer_layout_ready,
    parse_simulation,
    schedule_rollback,
    stage_release_package,
)
from mythos.util import MythOSError, read_json, write_json


def test_parse_apt_simulation() -> None:
    output = """Reading package lists... Done
Inst systemd [257.5-2] (257.6-1 Debian:13.1/stable [amd64])
Inst new-package (1.2.3 Debian-Security:13/stable-security [amd64])
Conf systemd (257.6-1 Debian:13.1/stable [amd64])
"""
    updates = parse_simulation(output)
    assert [(item.name, item.installed, item.candidate) for item in updates] == [
        ("systemd", "257.5-2", "257.6-1"),
        ("new-package", "not installed", "1.2.3"),
    ]
    assert [item.security for item in updates] == [False, True]


def test_parse_apt_simulation_ignores_noise() -> None:
    assert parse_simulation("0 upgraded, 0 newly installed, 0 to remove") == []


def test_consumer_layout_requires_separate_state_and_snapshots(monkeypatch) -> None:
    roots = {"/": "/@", "/.snapshots": "/@snapshots", "/var/lib/mythos": "/@state"}

    def fake_run(argv, **_kwargs):
        mountpoint = argv[-1]
        return CommandResult(list(argv), 0, f"btrfs {roots[mountpoint]}\n", "")

    monkeypatch.setattr("mythos.updates.run", fake_run)
    assert consumer_layout_ready()
    roots["/var/lib/mythos"] = "/@"
    assert not consumer_layout_ready()


def test_schedule_and_bless_rollback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MYTHOS_ROOT", str(tmp_path))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    (tmp_path / ".snapshots/7/snapshot").mkdir(parents=True)

    request = schedule_rollback(7, "test-transaction")
    assert request == tmp_path / ROLLBACK_REQUEST.removeprefix("/")
    assert request.read_text(encoding="utf-8") == "snapshot=7\ntransaction=test-transaction\n"

    state_path = tmp_path / "var/lib/mythos/update.json"
    write_json(state_path, {"status": "rollback-pending"})
    incomplete = bless_boot()
    assert incomplete["status"] == "failed"

    write_json(state_path, {"status": "rollback-pending"})
    complete = tmp_path / ROLLBACK_COMPLETE.removeprefix("/")
    complete.write_text("snapshot=7\n", encoding="utf-8")
    restored = bless_boot()
    assert restored["status"] == "rolled-back"
    assert not complete.exists()
    assert read_json(state_path, {})["status"] == "rolled-back"


def test_offline_update_link_must_target_mythos(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MYTHOS_ROOT", str(tmp_path))
    link = tmp_path / SYSTEM_UPDATE_LINK.removeprefix("/")
    link.symlink_to(SYSTEM_UPDATE_TARGET)
    assert _system_update_requested()
    link.unlink()
    link.symlink_to("/var/lib/another-updater")
    assert not _system_update_requested()


def test_signed_release_is_staged_for_offline_install(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MYTHOS_ROOT", str(tmp_path))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    package = tmp_path / "var/cache/mythos/releases/1.0.1/mythos-core_1.0.1_all.deb"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"signed package")
    monkeypatch.setattr("mythos.updates.snapshotter_ready", lambda: True)
    monkeypatch.setattr("mythos.updates._create_snapshot", lambda _description: 9)
    monkeypatch.setattr("mythos.updates.run", lambda argv, **_kwargs: CommandResult(list(argv), 0, "0 upgraded\n", ""))

    state = stage_release_package(package, "1.0.1", "rolling")
    assert state["kind"] == "release"
    assert state["status"] == "staged"
    assert _system_update_requested()


def test_release_stage_rejects_cache_prefix_confusion(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MYTHOS_ROOT", str(tmp_path))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    package = tmp_path / "var/cache/mythos/releases-evil/1.0.1/mythos-core_1.0.1_all.deb"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"not in the release cache")

    with pytest.raises(MythOSError, match="release cache"):
        stage_release_package(package, "1.0.1", "rolling")


def test_release_stage_rejects_invalid_signed_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MYTHOS_ROOT", str(tmp_path))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    package = tmp_path / "var/cache/mythos/releases/1.0.1/mythos-core_1.0.1_all.deb"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"signed package")

    with pytest.raises(MythOSError, match="metadata"):
        stage_release_package(package, "1.0.1", "preview")


def test_offline_release_rejects_outside_cache_before_mutating_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MYTHOS_ROOT", str(tmp_path))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    state_path = tmp_path / "var/lib/mythos/update.json"
    original = {
        "status": "staged",
        "kind": "release",
        "snapshot": 5,
        "transaction": "release-test",
        "release_package": str(tmp_path / "tmp/attacker.deb"),
    }
    write_json(state_path, original)
    link = tmp_path / SYSTEM_UPDATE_LINK.removeprefix("/")
    link.symlink_to(SYSTEM_UPDATE_TARGET)
    monkeypatch.setattr("mythos.updates.run", lambda *_args, **_kwargs: pytest.fail("apt must not run"))

    with pytest.raises(MythOSError, match="staged release package is invalid"):
        apply_offline_update()
    assert _system_update_requested()
    assert read_json(state_path, {}) == original
