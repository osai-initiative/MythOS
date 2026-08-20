from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_pipeline_requires_protected_signing_and_offline_safety() -> None:
    workflow = (ROOT / ".github/workflows/publish-release.yml").read_text(encoding="utf-8")
    builder = (ROOT / "scripts/build-release-update").read_text(encoding="utf-8")
    installer = (ROOT / "scripts/install-mythos-in-place").read_text(encoding="utf-8")

    assert "environment: release-signing" in workflow
    assert "MYTHOS_RELEASE_SIGNING_KEY" in workflow
    assert "gpg --batch --yes --armor --detach-sign" in builder
    assert "mythos-release-signing.gpg" in builder
    assert "EXPECTED_KEY_FINGERPRINT=5B32D10C7AFD29113A8023E4FA97765702948BA8" in installer
    assert "gpgv --keyring" in installer
    assert "apt-get install --yes --no-remove" in installer


def test_release_key_recovery_never_uploads_plaintext_private_key() -> None:
    workflow = (ROOT / ".github/workflows/recover-release-key.yml").read_text(encoding="utf-8")

    assert "--encrypt --recipient" in workflow
    assert "retention-days: 1" in workflow
    assert "--export-secret-keys" in workflow
    assert "actions/upload-artifact@v4" in workflow
