"use strict";
(() => {
  let pref="system";
  try{pref=localStorage.getItem("hch5-theme-preference")||"system"}catch(e){}
  const systemDark=matchMedia("(prefers-color-scheme: dark)").matches;
  const resolved=pref==="dark"?"dark":pref==="light"?"light":systemDark?"dark":"light";
  document.documentElement.dataset.theme=resolved;
  try{
    if(localStorage.getItem("hch5-sidebar-collapsed")==="1")document.documentElement.classList.add("sidebar-collapsed");
  }catch(e){}
  document.documentElement.classList.add("ui-prepaint");
  addEventListener("DOMContentLoaded",()=>{
    document.body.classList.toggle("sidebar-collapsed",document.documentElement.classList.contains("sidebar-collapsed"));
    const tab=new URLSearchParams(location.search).get("tab");
    if(location.pathname==="/"&&tab)history.replaceState(null,"","/");
    requestAnimationFrame(()=>document.documentElement.classList.remove("ui-prepaint"));
  },{once:true});
})();
