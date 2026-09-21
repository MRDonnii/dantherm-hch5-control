#!/usr/bin/env python3
"""RS485 mirror, decoder, WebUI host and disabled-by-default controller test runtime."""
import argparse, asyncio, logging, os, time
from pathlib import Path
import serial

from controller_core import HardwareAdapter
from controller_dashboard_server import ControllerDashboardHttpServer
from controller_runtime import ControllerRuntime
from passivelink_parser import DanthermDecoder, RtuStreamParser

LOG=logging.getLogger("passivelink-webui")
FIELD_MAP={
    "outdoor_temperature":"outdoor_temp","supply_temperature":"supply_temp",
    "extract_temperature":"extract_temp","exhaust_temperature":"exhaust_temp",
    "room_temperature":"room_temp","extract_fan_rpm":"fan_extract_rpm",
    "supply_fan_rpm":"fan_supply_rpm","extract_fan_percent":"fan_extract_percent",
    "supply_fan_percent":"fan_supply_percent","relative_humidity":"humidity",
    "filter_interval_days":"filter_interval","heat_recovery_raw":"heat_recovery_efficiency",
}

class Gateway:
    def __init__(self,device,bind,port,web_bind,web_port,preheater_url):
        self.device,self.bind,self.port=device,bind,port; self.clients=set(); self.running=True
        self.state={"gateway_mode":"passive_listener","control_status":"controller_disabled","bus_traffic":False,"bus_last_frame_age":None}
        self.last_frame=None; self.decoder=DanthermDecoder(self.on_update); self.parser=RtuStreamParser(self.on_frame)
        # Generic repo version intentionally has no physical write bindings.
        # The real Pi deploy must replace these None callbacks with the existing
        # hardware-verified monolithic-gateway functions before enabling control.
        self.controller=ControllerRuntime(gateway_state=self.state,hardware=HardwareAdapter())
        self.dashboard=ControllerDashboardHttpServer(
            web_bind,web_port,self.state,"Dantherm HCH5",preheater_url,
            controller_runtime=self.controller,
        )
    def on_frame(self,frame): self.last_frame=time.monotonic(); self.decoder.decode(frame)
    def on_update(self,values):
        for key,value in values.items(): self.state[FIELD_MAP.get(key,key)]=value
        self.state["available"]=True
    async def client(self,reader,writer):
        self.clients.add(writer)
        try:
            if await reader.read(1): LOG.warning("Disconnected TCP client that attempted to transmit")
        finally: self.clients.discard(writer); writer.close(); await writer.wait_closed()
    async def broadcast(self,data):
        failed=[]
        for writer in tuple(self.clients):
            try: writer.write(data); await writer.drain()
            except (ConnectionError,OSError): failed.append(writer)
        for writer in failed: self.clients.discard(writer); writer.close()
    async def health(self):
        while self.running:
            age=time.monotonic()-self.last_frame if self.last_frame else None
            self.state["bus_last_frame_age"]=round(age,1) if age is not None else None
            self.state["bus_traffic"]=age is not None and age<=5
            self.state["control_status"]=(
                self.controller.engine.resolve().get("effective_source")
                if self.controller.config.data.get("enabled") else "controller_disabled"
            )
            await asyncio.sleep(1)
    async def serial_loop(self):
        while self.running:
            connection=None
            try:
                if not Path(self.device).exists(): raise FileNotFoundError(self.device)
                connection=serial.Serial(self.device,19200,bytesize=8,parity=serial.PARITY_EVEN,stopbits=1,timeout=1,exclusive=True)
                connection.rts=False; connection.dtr=False; LOG.info("Listening on %s at 19200 8E1",self.device)
                while self.running:
                    data=await asyncio.to_thread(connection.read,4096)
                    if data: self.parser.feed(data); await self.broadcast(data)
            except (FileNotFoundError,OSError,serial.SerialException) as error:
                LOG.warning("RS485 unavailable (%s); retrying",error); await asyncio.sleep(3)
            finally:
                if connection and connection.is_open: connection.close()
    async def run(self):
        self.controller.start(); self.dashboard.start(); server=await asyncio.start_server(self.client,self.bind,self.port)
        LOG.info("Raw TCP listening on %s:%s; WebUI/controller on port %s",self.bind,self.port,self.dashboard.port)
        try:
            async with server: await asyncio.gather(server.serve_forever(),self.serial_loop(),self.health())
        finally:
            self.dashboard.stop(); self.controller.stop()

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--device",required=True); parser.add_argument("--bind",default=os.getenv("GATEWAY_BIND","0.0.0.0")); parser.add_argument("--port",type=int,default=int(os.getenv("GATEWAY_PORT","4196"))); parser.add_argument("--web-bind",default=os.getenv("WEBUI_BIND","0.0.0.0")); parser.add_argument("--web-port",type=int,default=int(os.getenv("WEBUI_PORT","8080"))); args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(Gateway(args.device,args.bind,args.port,args.web_bind,args.web_port,os.getenv("ONEWIRE_URL") or None).run())
if __name__=="__main__": main()
