import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "gateway" / "dantherm_pi_admin_api.py"


def load_module():
    os.environ.setdefault("DANTHERM_REBOOT_TOKEN", "test-token")
    sys.path.insert(0, str(ROOT / "gateway"))
    spec = importlib.util.spec_from_file_location("dantherm_pi_admin_api_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class UpdaterTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def setUp(self):
        self.module._UPDATE_INFO_CACHE.clear()
        self.module._UPDATE_INFO_CACHE_AT.clear()

    def test_beta_check_uses_public_release_feed_without_github_api(self):
        with (
            mock.patch.object(self.module, "current_version", return_value="1.2.0-beta.17"),
            mock.patch.object(self.module, "current_build", return_value="old"),
            mock.patch.object(
                self.module,
                "_request_text",
                return_value="<feed>v1.2.0-beta.17 v1.2.0-beta.20 v1.2.0-beta.19</feed>",
            ) as request_text,
            mock.patch.object(self.module, "_final_url") as final_url,
        ):
            info = self.module.update_info("beta")

        self.assertTrue(info["update_available"])
        self.assertEqual(info["available_build"], "1.2.0-beta.20")
        self.assertIn("github.com", request_text.call_args.args[0])
        self.assertIn("/releases.atom", request_text.call_args.args[0])
        self.assertEqual(info["ref"], "v1.2.0-beta.20")
        final_url.assert_not_called()

    def test_stable_check_resolves_public_latest_redirect(self):
        with (
            mock.patch.object(self.module, "current_version", return_value="1.1.0"),
            mock.patch.object(self.module, "current_build", return_value="old"),
            mock.patch.object(
                self.module,
                "_final_url",
                return_value="https://github.com/MRDonnii/dantherm-hch-passivelink-webui/releases/tag/v1.2.0",
            ),
        ):
            info = self.module.update_info("stable")

        self.assertEqual(info["ref"], "v1.2.0")
        self.assertEqual(info["available_version"], "1.2.0")
        self.assertTrue(info["update_available"])

    def test_download_uses_codeload_and_percent_encodes_branch(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.side_effect = [b"archive", b""]
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "source.tar.gz"
            with mock.patch.object(self.module.urllib.request, "urlopen", return_value=response) as urlopen:
                self.module._download_tarball("beta/1.1-modern-controller", destination)
            self.assertEqual(destination.read_bytes(), b"archive")

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://codeload.github.com/MRDonnii/dantherm-hch-passivelink-webui/tar.gz/beta%2F1.1-modern-controller",
        )
        self.assertNotIn("api.github.com", request.full_url)


if __name__ == "__main__":
    unittest.main()
