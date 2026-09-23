"""Regression test for FileNotFoundError/ESTALE on the admin update staging dir.

On NFS-backed root filesystems (e.g. diskless netboot Pi images), the
PrivateTmp per-service private bind mount for /tmp can go stale, which
surfaces to users as:

    FileNotFoundError: [Errno 2] No usable temporary directory found in
    ['/tmp', '/var/tmp', '/usr/tmp', '/']

when `_install_update` calls `tempfile.TemporaryDirectory()`. The fix routes
TMPDIR at a stable, already-writable state directory instead of relying on
the private /tmp bind mount.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_admin_service_sets_stable_tmpdir():
    text = (ROOT / "systemd/dantherm-webui-admin.service").read_text(encoding="utf-8")
    assert "Environment=TMPDIR=/var/lib/dantherm-admin/tmp" in text


def test_admin_service_creates_tmpdir_before_start():
    text = (ROOT / "systemd/dantherm-webui-admin.service").read_text(encoding="utf-8")
    assert "ExecStartPre=/usr/bin/install -d -m 0700 -o root -g root /var/lib/dantherm-admin/tmp" in text


def test_admin_service_still_declares_state_directory():
    text = (ROOT / "systemd/dantherm-webui-admin.service").read_text(encoding="utf-8")
    assert "StateDirectory=dantherm-admin" in text
