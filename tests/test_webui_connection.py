"""The WebUI stays connected: fast answers, no silent login loss, small polls."""
import gzip
import http.cookiejar
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from controller_dashboard_server import ControllerDashboardHttpServer
from dashboard_server import HistoryStore
from onewire_extras import OneWireExtras


class FakeRuntime:
    def snapshot(self):
        return {"enabled": True, "active_master": "pi", "decision_log": [{"level": 2, "reason": "Smart Auto"}] * 50,
                "change_log": [{"key": "mode"}], "decision_log_size": 50}

    def weather_snapshot(self):
        return {}


def slow_onewire_service(delay: float) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(delay)
            body = json.dumps({"available": True, "flow_temperature": 31.5, "return_temperature": 27.0}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class WebUIConnectionTests(unittest.TestCase):
    def start_server(self, tmp, preheater_url=None):
        server = ControllerDashboardHttpServer(
            "127.0.0.1", 0, {"bus_traffic": True, "bus_last_frame_age": 0.3}, "Test", preheater_url,
            web_root=ROOT / "gateway/webui", history_path=Path(tmp) / "history.sqlite3",
            controller_runtime=FakeRuntime(),
        )
        server.auth.path = Path(tmp) / "auth.json"
        server.auth.save("admin", "long-test-password", True)
        server.start()
        self.addCleanup(server.stop)
        return server, server.server.server_address[1]

    def login(self, port):
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        opener.open(urllib.request.Request(
            f"http://127.0.0.1:{port}/api/auth/login",
            data=json.dumps({"username": "admin", "password": "long-test-password"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        ))
        return opener

    def test_state_is_answered_at_once_while_the_onewire_service_is_slow(self):
        slow = slow_onewire_service(3.0)
        self.addCleanup(slow.server_close)
        self.addCleanup(slow.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            _, port = self.start_server(tmp, f"http://127.0.0.1:{slow.server_address[1]}/temperatures")
            opener = self.login(port)
            started = time.monotonic()
            state = json.load(opener.open(f"http://127.0.0.1:{port}/state.json", timeout=2))
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertTrue(state["available"])
            # The background refresher delivers the 1-Wire values shortly after.
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                state = json.load(opener.open(f"http://127.0.0.1:{port}/state.json", timeout=2))
                if state.get("flow_temperature") == 31.5:
                    break
                time.sleep(0.2)
            self.assertEqual(state.get("flow_temperature"), 31.5)

    def test_expired_session_gets_json_401_for_data_and_redirect_for_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, port = self.start_server(tmp)
            for path in ("/state.json", "/history.json?range=1h", "/api/controller/state", "/api/events"):
                with self.subTest(path=path):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}{path}")
                    self.assertEqual(error.exception.code, 401)
                    self.assertTrue(json.load(error.exception)["login_required"])
            self.assertTrue(urllib.request.urlopen(f"http://127.0.0.1:{port}/").geturl().endswith("/login"))

    def test_compact_controller_state_leaves_out_the_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, port = self.start_server(tmp)
            opener = self.login(port)
            full = json.load(opener.open(f"http://127.0.0.1:{port}/api/controller/state"))
            compact = json.load(opener.open(f"http://127.0.0.1:{port}/api/controller/state?compact=1"))
            self.assertIn("decision_log", full)
            self.assertIn("change_log", full)
            self.assertNotIn("decision_log", compact)
            self.assertNotIn("change_log", compact)
            self.assertEqual(compact["decision_log_size"], 50)

    def test_compact_controller_state_for_home_assistant_token(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"DANTHERM_CONTROLLER_TOKEN": "machine-token"}):
            _, port = self.start_server(tmp)
            request = urllib.request.Request(f"http://127.0.0.1:{port}/api/controller/state?compact=1",
                                             headers={"Authorization": "Bearer machine-token"})
            state = json.load(urllib.request.urlopen(request))
            self.assertTrue(state["enabled"])
            self.assertNotIn("decision_log", state)

    def test_json_is_gzipped_on_request_and_hashed_assets_are_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, port = self.start_server(tmp)
            opener = self.login(port)
            response = opener.open(urllib.request.Request(
                f"http://127.0.0.1:{port}/api/controller/state", headers={"Accept-Encoding": "gzip"}))
            self.assertEqual(response.headers["Content-Encoding"], "gzip")
            self.assertTrue(json.loads(gzip.decompress(response.read()))["enabled"])
            plain = opener.open(f"http://127.0.0.1:{port}/api/controller/state")
            self.assertIsNone(plain.headers["Content-Encoding"])
            bundle = next((ROOT / "gateway/webui").glob("v2-*.js")).name
            asset = opener.open(f"http://127.0.0.1:{port}/assets/{bundle}")
            self.assertIn("immutable", asset.headers["Cache-Control"])
            self.assertEqual(opener.open(f"http://127.0.0.1:{port}/").headers["Cache-Control"], "no-store")


class HistoryStrideTests(unittest.TestCase):
    def test_sql_thinning_keeps_the_same_rows_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp) / "history.sqlite3")
            now = int(time.time())
            with sqlite3.connect(store.path) as db:
                db.executemany("INSERT INTO samples (ts, co2) VALUES (?, ?)",
                               [(now - 60 * i, 400 + i) for i in range(2000)])
            rows = store.query("7d")
            everything = sorted(range(2000), reverse=True)
            stride = 2000 // 720
            self.assertEqual([row["co2"] for row in rows], [400 + i for i in everything[::stride]])
            self.assertNotIn("_row", rows[0])


class OneWireExtrasBusTests(unittest.TestCase):
    def test_water_pair_values_come_from_the_service_not_the_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            bus = Path(tmp)
            for sensor_id in ("28-flow", "28-return", "28-loft"):
                (bus / sensor_id).mkdir()
                (bus / sensor_id / "w1_slave").write_text("aa : crc=aa YES\naa t=21000\n", encoding="ascii")
            extras = OneWireExtras(lambda: {}, devices=bus, service_url="http://service")
            payload = {"flow_sensor": "28-flow", "return_sensor": "28-return",
                       "flow_temperature": 33.4, "return_temperature": 26.1}

            class Response:
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self): return json.dumps(payload).encode()

            read = []
            with patch("onewire_extras.urllib.request.urlopen", return_value=Response()), \
                    patch("onewire_extras.read_ds18b20", side_effect=lambda sensor_id, devices: read.append(sensor_id) or 21.0):
                extras.read_once(now=10.0)
            self.assertEqual(read, ["28-loft"])
            by_id = {sensor["id"]: sensor["temperature"] for sensor in extras.sensors(now=11.0)}
            self.assertEqual(by_id, {"28-flow": 33.4, "28-return": 26.1, "28-loft": 21.0})


if __name__ == "__main__":
    unittest.main()
