#!/usr/bin/env python3
"""Experimental local HCH controller state machine."""
from __future__ import annotations
import json, os, tempfile, threading, time
from pathlib import Path
FAN_LEVELS={1:(25,13),2:(55,43),3:(85,73),"boost":(100,88)}
VALID_MODES={"local_auto","smart_auto","manual"}
class ControllerError(ValueError): pass
class ControllerState:
 def __init__(self,path=None):
  self.path=Path(path or os.getenv("DANTHERM_CONTROLLER_STATE","/var/lib/dantherm/controller.json")); self.lock=threading.RLock()
  self.data={"enabled":False,"mode":"local_auto","local_level":2,"manual_level":2,"ha_demand":"normal","ha_last_seen":None,"ha_timeout_seconds":300,"effective_source":"disabled","effective_level":None,"bypass":"auto","fireplace":False,"updated_at":time.time()}; self.load()
 def load(self):
  try:
   saved=json.loads(self.path.read_text())
   for k in self.data:
    if k in saved:self.data[k]=saved[k]
  except (OSError,ValueError,TypeError):pass
 def save(self):
  self.path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=".controller-",dir=self.path.parent)
  try:
   with os.fdopen(fd,"w") as f: json.dump(self.data,f,indent=2,sort_keys=True); f.flush(); os.fsync(f.fileno())
   os.replace(tmp,self.path)
  finally:
   try: os.unlink(tmp)
   except OSError: pass
 def snapshot(self):
  with self.lock:
   d=dict(self.data); now=time.time(); seen=d.get("ha_last_seen"); d["ha_online"]=bool(seen and now-seen<=d["ha_timeout_seconds"]); d["ha_age_seconds"]=round(now-seen,1) if seen else None; return d
 def configure(self,patch):
  with self.lock:
   if "enabled" in patch:self.data["enabled"]=bool(patch["enabled"])
   if "mode" in patch:
    if patch["mode"] not in VALID_MODES:raise ControllerError("invalid mode")
    self.data["mode"]=patch["mode"]
   for key in ("local_level","manual_level"):
    if key in patch:
     value=patch[key]
     if value not in (1,2,3,"boost"):raise ControllerError("invalid fan level")
     self.data[key]=value
   if "ha_timeout_seconds" in patch:
    value=int(patch["ha_timeout_seconds"])
    if not 60<=value<=3600:raise ControllerError("HA timeout must be 60..3600 seconds")
    self.data["ha_timeout_seconds"]=value
   if "bypass" in patch:
    if patch["bypass"] not in ("auto","open","closed"):raise ControllerError("invalid bypass mode")
    self.data["bypass"]=patch["bypass"]
   if "fireplace" in patch:self.data["fireplace"]=bool(patch["fireplace"])
   self.data["updated_at"]=time.time(); self.save(); return self.resolve()
 def heartbeat(self,demand="normal"):
  if demand not in ("low","normal","high","boost"):raise ControllerError("invalid HA demand")
  with self.lock:self.data["ha_last_seen"]=time.time();self.data["ha_demand"]=demand;return self.resolve()
 def resolve(self):
  with self.lock:
   d=self.data; now=time.time()
   if not d["enabled"]:source,level="disabled",None
   elif d["mode"]=="manual":source,level="manual",d["manual_level"]
   elif d["mode"]=="smart_auto" and d.get("ha_last_seen") and now-d["ha_last_seen"]<=d["ha_timeout_seconds"]:source="ha_smart";level={"low":1,"normal":2,"high":3,"boost":"boost"}[d["ha_demand"]]
   else:source,level="local_fallback",d["local_level"]
   d["effective_source"],d["effective_level"]=source,level;d["updated_at"]=now;result=dict(d);result["fan_pair"]=FAN_LEVELS.get(level);return result
