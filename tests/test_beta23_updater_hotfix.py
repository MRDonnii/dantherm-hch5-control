from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_admin_service_allows_state_directory():
    text = (ROOT / 'systemd/dantherm-webui-admin.service').read_text(encoding='utf-8')
    assert '/var/lib/dantherm-hch5-ha' in text

def test_update_does_not_write_probe_state_before_service_upgrade():
    text = (ROOT / 'update.sh').read_text(encoding='utf-8')
    assert '.update-write-check' not in text
    assert 'Persistent state directory' in text

def test_manual_update_check_can_force_refresh():
    text = (ROOT / 'gateway/dantherm_pi_admin_api.py').read_text(encoding='utf-8')
    assert 'force_refresh: bool = False' in text
    assert 'update_info(channel, force_refresh=True)' in text
