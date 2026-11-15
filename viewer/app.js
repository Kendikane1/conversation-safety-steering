/* Copyright 2026 Muhammad Ariz Muhammad Akmal. SPDX-License-Identifier: MIT */
"use strict";
(() => {
  const data = window.PUBLIC_EVIDENCE;
  const el = id => document.getElementById(id);
  if (!data || !Array.isArray(data.rows)) {
    el("status").textContent = "The reviewed evidence bundle is unavailable. Check the release inventory and local viewer/data.js file.";
    return;
  }
  const rows = data.rows;
  const value = (r, k) => r[k] == null || r[k] === "" ? "(not applicable)" : String(r[k]);
  const filters = ["study", "family", "writer", "branch", "arm", "phase"];
  const fields = {study:"study",family:"family_id",writer:"writer",branch:"branch",arm:"arm",phase:"phase"};
  const option = (text, val) => { const o=document.createElement("option");o.textContent=text;o.value=val;return o; };
  function choices(id, input, keep=true) {
    const previous = keep ? el(id).value : "";
    el(id).replaceChildren(option("All", ""));
    [...new Set(input.map(r=>value(r,fields[id])))].sort().forEach(v=>el(id).append(option(v,v)));
    if ([...el(id).options].some(o=>o.value===previous)) el(id).value=previous;
  }
  choices("study",rows);
  if (rows.some(r=>r.study==="W03H-heldout")) el("study").value="W03H-heldout";
  function subset() {return rows.filter(r=>!el("study").value || value(r,"study")===el("study").value);}
  function otherChoices(){for(const id of filters.slice(1))choices(id,subset(),false);}
  function show(r) {
    if (!r) {el("record-title").textContent="No matching record";el("state").textContent="Change a filter to inspect another planned slot.";for(const id of ["labels","eligibility","measurement","source","answer","redactions"])el(id).textContent="";el("messages").replaceChildren();el("conversation").hidden=true;return;}
    el("record-title").textContent=r.row_id;
    el("state").textContent=`${r.study} · ${value(r,"phase")} · ${value(r,"status")}`;
    for (const id of ["labels","eligibility","measurement","source"]) el(id).textContent=JSON.stringify(r[id] ?? null,null,2);
    el("messages").replaceChildren();
    for(const message of (r.messages || [])){
      const section=document.createElement("section");section.className="message";
      const role=document.createElement("strong");role.textContent=String(message.role ?? "unknown role");
      const text=document.createElement("pre");text.textContent=String(message.content ?? "");
      section.append(role,text);el("messages").append(section);
    }
    el("answer").textContent=r.response == null ? "No observed answer in this exported row. See its status and eligibility; absence is not a safe outcome." : String(r.response);
    el("redactions").textContent=JSON.stringify(r.redactions ?? [],null,2);
    el("conversation").hidden=true;el("reveal").setAttribute("aria-expanded","false");el("reveal").textContent="Show reviewed conversation";
  }
  function update(){
    const query=el("search").value.trim().toLowerCase();
    const matches=subset().filter(r=>filters.slice(1).every(id=>!el(id).value || value(r,fields[id])===el(id).value) && (!query || [r.row_id,r.case_id,r.slot_id].some(v=>String(v??"").toLowerCase().includes(query))));
    el("record").replaceChildren();
    matches.forEach((r,i)=>el("record").append(option(`${r.row_id} · ${value(r,"status")}`,String(i))));
    el("status").textContent=`${matches.length} matching records of ${rows.length} exported rows. Counts include planned/excluded slots, context rows and separately labelled routing replays; they are not independent sample sizes.`;
    el("record").onchange=()=>show(matches[Number(el("record").value)]);
    if(matches.length)el("record").value="0";show(matches[0]);
  }
  el("study").onchange=()=>{otherChoices();update();};
  for(const id of filters.slice(1))el(id).onchange=update;
  el("search").oninput=update;
  el("reveal").onclick=()=>{const hidden=!el("conversation").hidden;el("conversation").hidden=hidden;el("reveal").setAttribute("aria-expanded",String(!hidden));el("reveal").textContent=hidden?"Show reviewed conversation":"Hide reviewed conversation";};
  otherChoices();if(el("study").value==="W03H-heldout")el("phase").value="crossed";update();
})();
