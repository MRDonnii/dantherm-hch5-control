import tempfile,time,unittest
from pathlib import Path
from controller_core import ControllerState
class ControllerTests(unittest.TestCase):
 def make(self):
  d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);return ControllerState(Path(d.name)/"state.json")
 def test_disabled(self):self.assertIsNone(self.make().resolve()["effective_level"])
 def test_local(self):
  c=self.make();r=c.configure({"enabled":True});self.assertEqual(r["fan_pair"],(55,43))
 def test_manual(self):
  c=self.make();r=c.configure({"enabled":True,"mode":"manual","manual_level":3});self.assertEqual(r["fan_pair"],(85,73))
 def test_smart(self):
  c=self.make();c.configure({"enabled":True,"mode":"smart_auto"});self.assertEqual(c.heartbeat("high")["effective_level"],3)
 def test_fallback(self):
  c=self.make();c.configure({"enabled":True,"mode":"smart_auto"});c.data["ha_last_seen"]=time.time()-999;self.assertEqual(c.resolve()["effective_source"],"local_fallback")
 def test_persist(self):
  c=self.make();c.configure({"local_level":3});self.assertEqual(ControllerState(c.path).data["local_level"],3)
if __name__=="__main__":unittest.main()
