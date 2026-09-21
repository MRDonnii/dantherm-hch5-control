"use strict";
(()=>{
  const $=s=>document.querySelector(s);
  const put=(id,value)=>{const el=$(id);if(el)el.textContent=value==null||value===""?"—":String(value)};
  const yesno=value=>value===true?"JA":value===false?"NEJ":"—";
  const age=value=>Number.isFinite(Number(value))?`${Number(value).toFixed(Number(value)<10?1:0)} s`:"—";
  function render(s){
    const master=s.active_master||"unknown";
    const labels={pi:"RASPBERRY PI",hcp4:"HCP4",unknown:"AFVENTER"};
    put("#active-master",labels[master]||master.toUpperCase());
    put("#hardware-writes-allowed",s.hardware_writes_allowed?"TILLADT":"BLOKERET");
    put("#hardware-control-state",String(s.hardware_control_state||"—").replaceAll("_"," ").toUpperCase());
    put("#hcp4-detected",yesno(s.hcp4_detected));
    put("#hcp4-write-age",age(s.hcp4_last_foreign_write_age));
    put("#hcp4-write-rate",`${s.hcp4_foreign_writes_10s??0} / ${s.hcp4_foreign_writes_60s??0}`);
    put("#pi-write-count",`${s.own_write_count??0} / ${s.own_echo_count??0}`);
    put("#master-age",age(s.master_age_seconds));
    put("#master-reason",String(s.hcp4_detection_reason||"—").replaceAll("_"," "));
    const badge=$("#master-badge");
    if(badge){badge.textContent=labels[master]||master.toUpperCase();badge.classList.toggle("safe",master==="pi");}
    const note=$("#master-note");
    if(note){
      if(master==="hcp4")note.textContent="HCP4 er aktiv master. Pi-controlleren er pauset og sender ingen RS485 control-writes.";
      else if(master==="pi")note.textContent="HCP4 er ikke registreret. Raspberry Pi er bekræftet master og må udføre controller-writes.";
      else note.textContent="Master er endnu ikke sikkert bestemt. Pi sender ingen controller-writes.";
    }
  }
  async function poll(){
    try{
      const response=await fetch("/api/controller/state",{cache:"no-store"});
      if(!response.ok)throw Error(response.status);
      render(await response.json());
    }catch(error){put("#active-master","FORBINDELSE TABT");put("#hardware-writes-allowed","BLOKERET");}
  }
  poll();setInterval(poll,2000);
})();
