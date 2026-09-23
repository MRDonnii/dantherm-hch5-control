import http.cookiejar, importlib.util, json, re, tempfile, time, unittest, urllib.error, urllib.request
from pathlib import Path
ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("dashboard_server", ROOT / "gateway/dashboard_server.py")
MODULE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)
class DashboardTests(unittest.TestCase):
    def test_gateway_availability_is_not_overwritten_by_onewire(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = MODULE.DashboardHttpServer("127.0.0.1", 0, {"bus_traffic": True, "bus_last_frame_age": 0.4}, "Test", None, web_root=ROOT / "gateway/webui", history_path=Path(tmp) / "history.sqlite3")
            self.assertTrue(server.snapshot()["available"])
    def test_recovery_uses_extract_exhaust_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"bus_traffic": True, "bus_last_frame_age": 0.2, "outdoor_temp": 12.0, "extract_temp": 19.2, "exhaust_temp": 12.6, "heat_recovery_efficiency": 151}
            server = MODULE.DashboardHttpServer("127.0.0.1", 0, state, "Test", None, web_root=ROOT / "gateway/webui", history_path=Path(tmp) / "history.sqlite3")
            snapshot = server.snapshot()
            self.assertAlmostEqual(snapshot["heat_recovery_efficiency"], 91.7, places=1)
            self.assertEqual(snapshot["heat_recovery_efficiency_raw"], 151)
    def test_recovery_remains_available_at_small_valid_temperature_span(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"bus_traffic": True, "bus_last_frame_age": 0.2, "outdoor_temp": 21.1, "extract_temp": 22.1, "exhaust_temp": 21.3}
            server = MODULE.DashboardHttpServer("127.0.0.1", 0, state, "Test", None, web_root=ROOT / "gateway/webui", history_path=Path(tmp) / "history.sqlite3")
            self.assertAlmostEqual(server.snapshot()["heat_recovery_efficiency"], 80.0, places=1)
    def test_history_rejects_invalid_recovery_and_applies_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MODULE.HistoryStore(Path(tmp) / "history.sqlite3", retention_days=1, sample_seconds=10); now = time.time()
            store.record({"co2": 800, "heat_recovery_efficiency": 151}, now=now - 90000); store.last_sample = 0
            store.record({"co2": 850, "heat_recovery_efficiency": 82}, now=now); rows = store.query("24h")
            self.assertEqual(len(rows), 1); self.assertEqual(rows[0]["co2"], 850); self.assertEqual(rows[0]["heat_recovery_efficiency"], 82)
    def test_server_serves_assets_and_has_no_write_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = MODULE.DashboardHttpServer("127.0.0.1", 0, {"bus_traffic": True, "bus_last_frame_age": 0.2}, "Test", None, web_root=ROOT / "gateway/webui", history_path=Path(tmp) / "history.sqlite3"); server.start(); port = server.server.server_address[1]
            try:
                server.auth.path=Path(tmp)/"auth.json"; server.auth.save("admin","long-test-password",False)
                index = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read()
                self.assertIn(b"HCH5 Control", index)
                self.assertIn(b"/assets/v2-", index)
                self.assertIn(b":root", urllib.request.urlopen(f"http://127.0.0.1:{port}/assets/dashboard.css").read())
                self.assertTrue(json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/state.json"))["available"])
                request = urllib.request.Request(f"http://127.0.0.1:{port}/api/control", data=b"{}", method="POST")
                with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 405)
            finally: server.stop()
    def test_basic_auth_protects_dashboard(self):
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
        # Oriented like the real HCH5: outdoor air enters on the right.
        filter_x = {
            label: int(x) for x, label in re.findall(r'<Filter x=\{(\d+)\}[^>]*? label="(Filter · \w+)"', diagram)
        }
        self.assertGreater(filter_x["Filter · udeluft"], filter_x["Filter · udsugning"])
        self.assertIn("Ekstern eftervarme · HAC1", diagram)
        self.assertIn("Bypass-spjæld", diagram)
        self.assertIn("afterheat_setpoint", overview)
        self.assertNotIn("afterheat_valve", overview)
        self.assertIn("HAC1 regulerer selv varmefladen", overview)
        self.assertIn('["/technique", "Teknik", Gauge]', shell)
        self.assertIn('["/updates", "Opdateringer", RefreshCw]', shell)
        self.assertIn('availableUpdate && <NavLink className="topbar-update-tab" to="/updates"', shell)
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
