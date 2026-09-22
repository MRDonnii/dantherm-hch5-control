import http.cookiejar
import importlib.util
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; GW=ROOT/"gateway"
spec=importlib.util.spec_from_file_location("dashboard_server",GW/"dashboard_server.py"); MODULE=importlib.util.module_from_spec(spec); spec.loader.exec_module(MODULE)

class DashboardTests(unittest.TestCase):
    def test_auth_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = MODULE.DashboardHttpServer("127.0.0.1", 0, {}, "Test", None, web_root=ROOT / "gateway/webui", history_path=Path(tmp) / "history.sqlite3")
            server.auth.path=Path(tmp)/"auth.json"; server.auth.save("admin","long-test-password",True); server.start(); port = server.server.server_address[1]
            try:
                self.assertTrue(urllib.request.urlopen(f"http://127.0.0.1:{port}/").geturl().endswith("/login"))
                opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                request=urllib.request.Request(f"http://127.0.0.1:{port}/api/auth/login",data=json.dumps({"username":"admin","password":"long-test-password"}).encode(),headers={"Content-Type":"application/json"},method="POST")
                self.assertEqual(opener.open(request).status,200); self.assertIn(b"HCH5 Control",opener.open(f"http://127.0.0.1:{port}/").read())
            finally: server.stop()

    def test_webui_v2_airflow_and_navigation_contract(self):
        overview = (ROOT / "frontend-v2/src/pages/OverviewPage.tsx").read_text()
        diagram = (ROOT / "frontend-v2/src/components/Hch5UnitDiagram.tsx").read_text()
        shell = (ROOT / "frontend-v2/src/components/AppShell.tsx").read_text()
        app = (ROOT / "frontend-v2/src/App.tsx").read_text()
        main = (ROOT / "frontend-v2/src/main.tsx").read_text()
        self.assertIn("Luftstrømme og temperaturer", overview)
        self.assertIn("Filter · udeluft", diagram)
        self.assertIn("Filter · udsugning", diagram)
        self.assertLess(diagram.index("Filter · udeluft"), diagram.index("Filter · udsugning"))
        self.assertIn("Eftervarme · vandflade", diagram)
        self.assertIn("Bypass-spjæld", diagram)
        self.assertIn("afterheat_setpoint", overview)
        self.assertNotIn("afterheat_valve", overview)
        self.assertIn("HAC1 regulerer selv varmefladen", overview)
        self.assertIn('["/technique", "Teknik", Gauge]', shell)
        self.assertIn('["/updates", "Opdateringer", RefreshCw]', shell)
        self.assertIn('path="/technique"', app)
        self.assertIn('path="/updates"', app)
        self.assertIn("<UpdatesPage />", app)
        self.assertIn("HashRouter", main)
        self.assertNotIn("<iframe", app.lower())
        self.assertNotIn("window.location.assign(\"/controller\")", shell)

    def test_read_only_system_snapshot_has_no_control_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = MODULE.DashboardHttpServer("127.0.0.1", 0, {}, "Test", None, web_root=ROOT / "gateway/webui", history_path=Path(tmp) / "history.sqlite3")
            snapshot = server.snapshot()
            self.assertIn("system_hostname", snapshot)
            self.assertIn("network_stack", snapshot)
            self.assertFalse(any(key.startswith(("password", "secret", "token")) for key in snapshot))

if __name__ == "__main__": unittest.main()
