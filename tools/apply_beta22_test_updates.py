from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def patch(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"marker not found: {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")

patch(
    "tests/test_controller_runtime.py",
    '''    def test_rh_room_and_fast_rise_raise_level(self):\n        runtime = self.make_runtime()\n        self.assertGreaterEqual(self.decision(runtime, {"Bath": {"humidity": 58}}), 5)\n        runtime = self.make_runtime()\n        runtime._room_rh_history["Bath"].append((time.time() - 300, 48.0))\n        self.assertGreaterEqual(self.decision(runtime, {"Bath": {"humidity": 56}}), 5)\n        self.assertEqual(runtime.smart_controlling_metric, "rh_rise")\n''',
    '''    def test_bathroom_rh_uses_separate_threshold_and_level_cap(self):\n        runtime = self.make_runtime()\n        runtime.config.configure({\n            "bathroom_rh_setpoint": 65,\n            "bathroom_rh_hysteresis": 5,\n            "bathroom_max_level": 4,\n        })\n        # A bathroom can be humid without immediately forcing full boost.\n        self.assertLessEqual(self.decision(runtime, {"Bath": {"humidity": 58}}), 4)\n        self.assertEqual(self.decision(runtime, {"Bath": {"humidity": 78}}), 4)\n        # A shower-like fast rise is still recognised, but remains capped.\n        runtime = self.make_runtime()\n        runtime.config.configure({"bathroom_max_level": 4})\n        runtime._room_rh_history["Bath"].append((time.time() - 300, 48.0))\n        self.assertLessEqual(self.decision(runtime, {"Bath": {"humidity": 68}}), 4)\n        self.assertEqual(runtime.smart_controlling_metric, "rh_rise")\n\n    def test_normal_room_rh_keeps_global_policy(self):\n        runtime = self.make_runtime()\n        self.assertGreaterEqual(\n            self.decision(runtime, {"Utility": {"humidity": 58, "room_type": "normal"}}),\n            5,\n        )\n''',
)

patch(
    "tests/test_modern_automation.py",
    '''        engine.update_measurements(rh=70, co2=1600)\n        engine.current_auto_level = 5\n        result = engine.resolve(now=time.time())\n        self.assertGreaterEqual(result["effective_level"], 5)\n''',
    '''        engine.update_measurements(rh=70, co2=1600)\n        engine.current_auto_level = 5\n        result = engine.resolve(now=time.time())\n        # Air quality may lift night mode, but the configured night ceiling\n        # prevents the two policies from fighting all the way to full boost.\n        self.assertEqual(result["effective_level"], 4)\n        self.assertEqual(result["effective_source"], "night_air_quality")\n''',
)

patch(
    "tests/test_dashboard_server.py",
    '        self.assertIn("Eftervarme · vandflade", diagram)\n',
    '        self.assertIn("Ekstern eftervarme · HAC1", diagram)\n',
)

# Keep the existing navigation regression contract readable/stable.
patch(
    "frontend-v2/src/App.tsx",
    '<Route path="/updates" element={<UpdatesPage/>}/>',
    '<Route path="/updates" element={<UpdatesPage />}/>',
)

print("beta.22 test contracts updated")
