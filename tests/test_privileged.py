from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from mythos.privileged import action_for, authorize_sender, execute
from mythos.util import MythOSError


def test_operations_use_distinct_polkit_actions() -> None:
    assert action_for(["drivers", "install-recommended"]) == "org.mythos.control.drivers-install"
    assert action_for(["update", "channel", "current"]) == "org.mythos.control.update-channel"
    assert action_for(["preference", "macos-preview", "enabled", "--acknowledge-compatibility-warning"]) == "org.mythos.control.preference-set"


def test_every_feature_has_a_polkit_action() -> None:
    root = ET.parse("data/polkit/org.mythos.control.policy").getroot()
    action_ids = {action.attrib["id"] for action in root.findall("action")}
    for feature in ("windows-apps", "gaming", "appimages", "local-ai", "backup-plus", "developer", "virtualization", "native-packages", "snap"):
        assert f"org.mythos.control.feature-{feature}" in action_ids


@pytest.mark.parametrize(
    "argv",
    [
        ["drivers", "firmware", "extra"],
        ["update", "channel", "testing"],
        ["preference", "unknown", "enabled"],
        ["snapshots", "rollback", "0"],
        ["recovery", "repair-bootloader", "/dev/sda"],
    ],
)
def test_operation_allowlist_rejects_unapproved_requests(argv: list[str]) -> None:
    with pytest.raises(MythOSError, match="not allowed"):
        action_for(argv)


def test_authorization_is_bound_to_calling_bus_name(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        captured.extend(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("mythos.privileged.subprocess.run", fake_run)
    authorize_sender(":1.42", "org.mythos.control.drivers-install")
    assert captured == [
        "pkcheck",
        "--action-id",
        "org.mythos.control.drivers-install",
        "--system-bus-name",
        ":1.42",
        "--allow-user-interaction",
    ]


def test_execute_revalidates_fixed_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        captured.extend(argv)
        return SimpleNamespace(returncode=0, stdout='{"message":"ok"}\n', stderr="")

    monkeypatch.setattr("mythos.privileged.subprocess.run", fake_run)
    assert execute(["drivers", "install-recommended"]) == {"message": "ok"}
    assert captured == ["/usr/bin/mythosctl", "--compact", "drivers", "install-recommended"]
