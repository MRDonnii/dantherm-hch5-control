import { chromium } from '../frontend-v2/node_modules/playwright-core/index.mjs';
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
const browser = await chromium.launch({executablePath:'/usr/bin/google-chrome', headless:true, args:['--no-sandbox']});
const output = new URL('../docs/images/1.3.2/', import.meta.url).pathname;
const previewOrigin = process.env.PREVIEW_ORIGIN || 'http://127.0.0.1:5173';
const version = readFileSync(new URL('../VERSION', import.meta.url),'utf8').trim();
mkdirSync(output,{recursive:true});
const unit = {available:true,bus_traffic:true,outdoor_temp:8.4,extract_temp:21.7,exhaust_temp:11.2,heating_coil_after_temperature:20.9,heating_coil_frost_temperature:8.1,flow_temperature:34.2,return_temperature:28.1,fan_supply_rpm:1740,fan_extract_rpm:1790,fan_supply_percent:64,fan_extract_percent:66,humidity:46,co2:620,filter_life_percent:86,bypass_active:false,bypass_raw:0,bypass_request:'AUTO',bus_frame_rate:217,bus_last_frame_age:0.4,service_gateway_activestate:'active',service_admin_activestate:'active',service_onewire_activestate:'active',service_ssh_activestate:'active',system_hostname:'hch5-control',system_model:'Raspberry Pi 3 Model B Rev 1.2',pi_model:'Raspberry Pi 3 Model B Rev 1.2',system_os:'Raspberry Pi OS 12 (bookworm)',system_kernel:'6.6.51+rpt-rpi-v7',system_architecture:'armv7l',system_python_version:'3.11.2',system_boot_mode:'SD-kort',system_cpu_count:4,system_cpu_frequency_mhz:1200,system_cpu_temperature:47.2,pi_cpu_temperature:47.2,system_cpu_usage_percent:9,system_load_1m:0.31,system_load_5m:0.27,system_load_15m:0.25,system_memory_total_bytes:969000000,system_memory_used_bytes:312000000,system_memory_used_percent:32,system_root_used_gb:4.1,system_root_free_gb:24.6,system_root_used_percent:14,system_uptime_seconds:604800,pi_uptime_seconds:604800,system_boot_time:'2026-09-20T08:00:00',system_hch5_version:'1.3.2',network_interface:'eth0',network_ipv4:'192.168.1.50/24',network_gateway:'192.168.1.1',network_link_speed_mbps:100,network_rx_bytes:1830000000,network_tx_bytes:2410000000};
const controller = {active_master:'pi',rs485_healthy:true,mode:'smart_auto',effective_level:3,unit_power_w:58,attic_temperature:18.2,actual_supply_air_temperature:20.9,actual_supply_before_heater_temperature:19.7,actual_afterheat_frost_temperature:8.1,actual_fan_supply_rpm:1740,actual_fan_extract_rpm:1790,actual_fan_supply_percent:64,actual_fan_extract_percent:66,actual_bypass:false,actual_bypass_raw:0,actual_bypass_request:'AUTO',actual_afterheat:true,afterheat_setpoint:21,afterheat_enabled:true,actual_afterheat_selection:21,afterheat_coil:'water',supply_airflow_estimate_m3h:145,supply_recovery_percent:76,recovered_heat_w:690,afterheat_lift:1.2,afterheat_power_w:58,diagnostics_status:'ok',diagnostics_alarm_count:0,frost_state:'ok',filter_power_ratio:1.04,specific_fan_power:390,recovered_energy_today_kwh:4.28,unit_energy_today_kwh:1.1,unit_energy_measured_today_kwh:1.37,afterheat_energy_today_kwh:0.36,electricity_price_dkk_kwh:2.06,heat_price_dkk_kwh:0.596,hardware_writes_allowed:true,hardware_control_state:'ready',hcp4_detected:false,hcp4_detection_reason:'HCP4 frakoblet',hcp4_foreign_writes_10s:0,hcp4_foreign_writes_60s:0,own_write_count:42,own_echo_count:42,write_failures:0,retry_limit:3,master_age_seconds:0.4,master_bus_frame_age:0.4,controller_uptime_seconds:604800,effective_source:'smart_auto',effective_reason:'CO₂ i soveværelse',ha_online:true,ha_age_seconds:12,smart_inputs_online:true,smart_inputs_age_seconds:12,smart_inputs_valid_for_seconds:180,smart_demand:3,smart_requested_level:3,smart_controlling_room:'Soveværelse',smart_controlling_metric:'co2',smart_max_co2:780,smart_max_co2_room:'Soveværelse',smart_max_rh:58,smart_max_rh_room:'Badeværelse',smart_reason:'CO₂ 780 ppm',smart_ha_rooms:{'Soveværelse':{name:'Soveværelse',room_type:'bedroom',priority:'auto',control:true,co2:780,temperature:21.2,humidity:48},'Badeværelse':{name:'Badeværelse',room_type:'bathroom',priority:'high',control:true,humidity:58,temperature:23.1},'Køkken':{name:'Køkken',room_type:'kitchen',priority:'auto',control:true,co2:640,temperature:22.4},'Stue':{name:'Stue',room_type:'living',priority:'auto',control:false,temperature:22.0,humidity:45}},onewire_sensors:[{id:'28-0000000000a1',temperature:19.7,role:'t2',name:''},{id:'28-0000000000a2',temperature:34.2,role:'water_flow',name:''},{id:'28-0000000000a3',temperature:28.1,role:'water_return',name:''},{id:'28-0000000000a4',temperature:18.2,role:'attic',name:''}],onewire_roles:{'28-0000000000a1':{role:'t2',name:''},'28-0000000000a4':{role:'attic',name:''}}};
controller.schedule_enabled = true;
controller.schedule_periods = Object.fromEntries(Array.from({length: 7}, (_, day) => [String(day), day < 5 ? [
  {start:'07:00', end:'09:00', level:3, mode:'min', label:'Morgen'},
  {start:'09:00', end:'16:00', level:1, mode:'set', label:'Arbejdstid'},
  {start:'17:00', end:'22:00', level:3, mode:'min', label:'Hjemme'},
] : [{start:'08:00', end:'22:00', level:3, mode:'min', label:'Weekend'}]]));
const now=Math.floor(Date.parse('2026-09-26T14:00:00Z')/1000);
const history=Array.from({length:288},(_,i)=>{const ts=now-86400+i*300,h=((i*5/60)+14)%24,day=Math.sin((h-9)/24*2*Math.PI),out=8+5*day,ext=21.4+0.5*day,eff=0.86;return {ts,outdoor_temp:+out.toFixed(2),extract_temp:+ext.toFixed(2),supply_temp:+(out+eff*(ext-out)+0.8).toFixed(2),exhaust_temp:+(ext-eff*(ext-out)).toFixed(2),flow_temperature:+(34+3*Math.cos(h*Math.PI/4)).toFixed(2),return_temperature:+(28+2*Math.cos(h*Math.PI/4)).toFixed(2),co2:Math.round(560+(h>21||h<7?280:90)+40*Math.sin(i/7)),fan_supply_rpm:h>22||h<6?1380:1740,fan_extract_rpm:h>22||h<6?1420:1790,heat_recovery_efficiency:+(86+2*Math.sin(h*Math.PI/12)).toFixed(1),system_cpu_usage_percent:Math.round(8+4*Math.abs(Math.sin(i/5))),pi_cpu_temperature:+(46+2*Math.sin(i/9)).toFixed(1),system_memory_used_percent:+(31+Math.sin(i/30)).toFixed(1)}});
async function setup(width,height,theme='dark',path='overview'){
 const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
 await page.addInitScript(t => { localStorage.setItem('hch5-weather-place', JSON.stringify({name:'Eksempel',latitude:56,longitude:10})); localStorage.setItem('hch5-v2-theme', t); }, theme);
 await page.route('**/assets/brand-mark.svg',route=>route.fulfill({path:new URL('../gateway/webui/brand-mark.svg',import.meta.url).pathname,contentType:'image/svg+xml'}));
 await page.route('**/state.json',route=>route.fulfill({json:unit}));
 await page.route('**/api/controller/state',route=>route.fulfill({json:controller}));
 await page.route('**/history.json*',route=>route.fulfill({json:{range:'24h',samples:history}}));
 await page.route('**/api/auth/status',route=>route.fulfill({json:{configured:true,enabled:true,authenticated:true,username:'Demo',role:'admin',role_label:'Administrator',permissions:['control','configure','diagnostics','system','mail','users','login_switch'],csrf:'demo'}}));
 await page.route('**/api/balancing',route=>route.fulfill({json:{project:{rooms:[{id:'living',name:'Stue',type:'living',area:36,height:2.5,supply:true,extract:false,measured_supply:null,measured_extract:null,valve_supply:'',valve_extract:'',note:''},{id:'bath',name:'Badeværelse',type:'bathroom',area:10,height:2.5,supply:false,extract:true,measured_supply:null,measured_extract:null,valve_supply:'',valve_extract:'',note:''}],meta:{site:'Eksempel',address:'',owner:'',technician:'',company:'',instrument:'',notes:''},measure_level:null},reports:[]}}));
 await page.route('**/api/events*',route=>route.fulfill({json:{events:[],active:[]}}));
 await page.route('**/api/users',route=>route.fulfill({json:{users:[{username:'Demo',role:'admin',email:'',disabled:false,expires_at:null,expired:false}]}}));
 await page.route('**/api/mail',route=>route.fulfill({json:{enabled:false,host:'',port:587,security:'starttls',username:'',password_set:false,from_address:'',from_name:'',recipients:[],alerts_enabled:false,alert_min_severity:'warning',alert_resolved:true,alert_repeat_hours:24,password_reset_enabled:false,base_url:'',configured:false,log:[]}}));
 await page.route('**/api/admin/action',route=>{const action=(route.request().postDataJSON()||{}).action;
  if(action==='get_system_status')return route.fulfill({json:{power_profile:'balanced',available_profiles:['powersave','balanced','performance'],governor:'ondemand',network_manager_available:true,wifi_available:true,wifi_enabled:false,wifi_connection:null,wifi_ipv4:null,bluetooth_available:false,networks:[]}});
  return route.fulfill({json:{current_version:version,available_version:version,current_build:'example',available_build:'example',channel:'stable',update_available:false}});});
 await page.route('https://api.open-meteo.com/**',route=>route.fulfill({json:{current:{temperature_2m:9.2,weather_code:2,is_day:1,time:'2026-09-26T14:00'}}}));
 await page.route('https://air-quality-api.open-meteo.com/**',route=>route.fulfill({json:{current:{european_aqi:24,pm2_5:5.2,pm10:9.1,time:'2026-09-26T14:00'}}}));
 await page.goto(`${previewOrigin}/assets/#/${path}`);
 if(path==='overview') await page.waitForSelector('.hch-water-coil.active');
 await page.waitForTimeout(600);
 return page;
}
const desktop=await setup(1600,900);
await desktop.screenshot({path:output+'overview-desktop.png',fullPage:true});
const frames=mkdtempSync(join(tmpdir(),'hch5-gif-'));
for(let i=0;i<20;i++){await desktop.locator('.pro-air-card').screenshot({path:join(frames,`frame-${String(i).padStart(2,'0')}.png`)});await desktop.waitForTimeout(110);}
execFileSync('convert',['-delay','11','-loop','0',...Array.from({length:20},(_,i)=>join(frames,`frame-${String(i).padStart(2,'0')}.png`)),'-colors','128','-layers','Optimize',output+'overview-animation.gif']);
rmSync(frames,{recursive:true,force:true});
// Whole front page in the dark theme, animated.
const pageFrames=mkdtempSync(join(tmpdir(),'hch5-page-gif-'));
for(let i=0;i<24;i++){await desktop.screenshot({path:join(pageFrames,`frame-${String(i).padStart(2,'0')}.png`),fullPage:true});await desktop.waitForTimeout(90);}
execFileSync('convert',['-delay','12','-loop','0',...Array.from({length:24},(_,i)=>join(pageFrames,`frame-${String(i).padStart(2,'0')}.png`)),'-resize','1200x','-colors','160','-layers','Optimize',output+'overview-page-dark.gif']);
rmSync(pageFrames,{recursive:true,force:true});
const mobile=await setup(390,844);
await mobile.screenshot({path:output+'overview-mobile.png',fullPage:true});
const light=await setup(1600,900,'light');
await light.screenshot({path:output+'overview-light.png',fullPage:true});
await light.close();
async function shot(path,file,wait){await desktop.goto(`${previewOrigin}/assets/#/${path}`);await desktop.reload();if(wait)await desktop.waitForSelector(wait);await desktop.waitForTimeout(1200);await desktop.screenshot({path:output+file,fullPage:true});}
await shot('history','history.png');
await shot('schedule','schedule.png');
await shot('balancing','balancing.png');
await shot('technique','technique.png');
await shot('settings?section=air','settings-air-quality.png');
await shot('settings?section=afterheat','settings-afterheat.png');
await shot('settings?section=sensors','settings-sensors.png');
await shot('settings?section=users','settings-users.png');
await shot('settings?section=mail','settings-mail.png');
await shot('home-assistant','home-assistant.png','.panel-grid');
await shot('updates','updates-home-assistant.png','.update-ha-links');
await shot('system','system.png');
await shot('diagnostics','diagnostics.png');
const login=await browser.newPage({viewport:{width:480,height:800},deviceScaleFactor:1});
await login.route('**/api/auth/status',route=>route.fulfill({json:{configured:false,authenticated:false}}));
await login.route('**/assets/**',route=>route.fulfill({path:new URL('../gateway/webui/'+new URL(route.request().url()).pathname.split('/').pop(),import.meta.url).pathname}));
await login.goto(`${previewOrigin}/assets/login.html`);
await login.waitForTimeout(1000);
await login.screenshot({path:output+'first-user-setup.png'});
await login.close();
await desktop.close();await mobile.close();await browser.close();
