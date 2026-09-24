import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
os.environ.setdefault("DANTHERM_REBOOT_TOKEN", "test-token")
spec = importlib.util.spec_from_file_location("system_network_admin_test", ROOT / "gateway/dantherm_pi_admin_api.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class SystemNetworkAdminTests(unittest.TestCase):
    def test_saved_profile_unavailable_does_not_stop_admin_api(self):
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "power-profile"
            saved.write_text("balanced\n")
            with mock.patch.object(module, "PROFILE_FILE", saved), mock.patch.object(module, "set_profile", side_effect=ValueError("profile_unavailable")), mock.patch.object(module, "ThreadingHTTPServer") as server:
                module.main()
            server.return_value.serve_forever.assert_called_once()

    def test_nmcli_escaped_ssid_fields(self):
        self.assertEqual(module._nmcli_fields(r"*:Kitchen\: guest:78:WPA2"), ["*", "Kitchen: guest", "78", "WPA2"])

    def test_scan_deduplicates_and_sorts_without_credentials(self):
        output = "*:Home:74:WPA2\n:Home:44:WPA2\n:Guest:89:WPA2\n"
        with mock.patch.object(module, "system_status", return_value={"wifi_available": True}), mock.patch.object(module, "_nmcli", return_value=output) as nmcli:
            networks = module.wifi_scan()
        self.assertEqual([item["ssid"] for item in networks], ["Home", "Guest"])
        self.assertTrue(networks[0]["connected"])
        self.assertNotIn("password", " ".join(nmcli.call_args.args))

    def test_connect_passes_password_only_through_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def fake_nmcli(*args, **kwargs):
                calls.append(args)
                if "passwd-file" in args:
                    path = Path(args[args.index("passwd-file") + 1])
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(path.read_text(), "802-11-wireless-security.psk:secret-passphrase\n")
                return ""
            with mock.patch.object(module, "PROFILE_FILE", Path(directory) / "power-profile"), mock.patch.object(module, "system_status", return_value={"wifi_available": True}), mock.patch.object(module, "_nmcli", side_effect=fake_nmcli):
                module.wifi_connect({"ssid": "Home", "password": "secret-passphrase"})
            self.assertTrue(any("ipv4.route-metric" in args for args in calls))
            self.assertNotIn("secret-passphrase", repr(calls))
            self.assertEqual(list(Path(directory).glob("wifi-pass-*")), [])

    def test_rejects_invalid_wifi_input_before_network_command(self):
        with mock.patch.object(module, "_nmcli") as nmcli:
            with self.assertRaises(ValueError):
                module.wifi_connect({"ssid": "Bad\nName", "password": "secret-passphrase"})
            with self.assertRaises(ValueError):
                module.wifi_connect({"ssid": "Home", "password": "short"})
            nmcli.assert_not_called()


if __name__ == "__main__":
    unittest.main()
