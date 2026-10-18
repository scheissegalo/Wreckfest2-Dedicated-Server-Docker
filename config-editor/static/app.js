/* Wreckfest 2 Config Editor — SPA logic (vanilla JS, no build step) */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

let game = null;          // scanned game metadata
let configs = [];         // [{name, size, mtime}]
let scnf = null;          // server_config.scnf content (deep-cloned per edit)
let scnfName = "server_config.scnf";
let loopName = null;      // currently edited .becl
let loopData = null;      // deep clone
let cupsName = "server_cup_config.ccnl";
let cupsData = null;      // deep clone
let dirty = false;

/* ---------------- API helpers ---------------- */

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
}

function setDirty(v) {
  dirty = v;
  $("#dirty-indicator").hidden = !v;
}

function status(el, msg, isErr = false) {
  el.textContent = msg;
  el.classList.toggle("err", isErr);
  if (msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 4000);
}

/* ---------------- Tabs ---------------- */

$$("#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});
$$("a[data-goto]").forEach((a) => {
  a.addEventListener("click", (e) => { e.preventDefault(); showTab(a.dataset.goto); });
});

function showTab(name) {
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "backups") loadBackups();
  if (name === "raw") loadRaw();
  if (name === "loop" && loopData) renderEvents();
  if (name === "cups" && cupsData) renderCups();
}

window.addEventListener("beforeunload", (e) => {
  if (dirty) { e.preventDefault(); e.returnValue = ""; }
});

/* ---------------- Boot ---------------- */

async function boot() {
  game = await api("/api/game-data");
  configs = await api("/api/configs");

  const scnfCfg = configs.find((c) => c.name === "server_config.scnf")
    || configs.find((c) => c.name.endsWith(".scnf"));
  if (!scnfCfg) throw new Error("server_config.scnf not found in config dir");
  scnfName = scnfCfg.name;
  scnf = (await api(`/api/config/${scnfCfg.name}`)).content;

  const loopFiles = configs.filter((c) => c.name.endsWith(".becl")).map((c) => c.name);
  $("#loop-files").innerHTML = loopFiles.map((f) => `<option value="${f.replace(/\.becl$/, "")}">`).join("");

  cupsName = configs.find((c) => c.name.endsWith(".ccnl"))?.name || "server_cup_config.ccnl";
  if (configs.some((c) => c.name === cupsName)) {
    cupsData = (await api(`/api/config/${cupsName}`)).content;
  } else {
    cupsData = { cups: [] };
  }

  renderServerTab();
  populateLoopSelect(loopFiles);
  populateLoopSelect2(loopFiles);
  const active = scnf["game server config"]?.[0]?.["event loop name"] || "";
  const pick = loopFiles.find((f) => f.replace(/\.becl$/, "") === active) || loopFiles[0];
  if (pick) await loadLoop(pick);
}

/* ---------------- Server tab ---------------- */

function net() { return scnf["net server config"][0]; }
function gameCfg() { return scnf["game server config"][0]; }

function renderServerTab() {
  $("#srv-name").value = net().name ?? "";
  $("#srv-desc").value = net().description ?? "";
  $("#srv-pass").value = net().password ?? "";
  $("#srv-port").value = net()["game port"] ?? 30100;
  $("#srv-cuplist").value = gameCfg()["cup list"] ?? "";
  $("#srv-countdown").value = gameCfg()["countdown time"] ?? 60000;
  $("#srv-voting").value = gameCfg()["voting time"] ?? 20000;

  const flagsBox = $("#srv-flags");
  flagsBox.querySelectorAll(".chkrow").forEach((n) => n.remove());
  const current = (gameCfg().flags || "").split(",").map((s) => s.trim()).filter(Boolean);
  for (const f of game.server_flags) {
    const row = document.createElement("label");
    row.className = "chkrow";
    row.innerHTML = `<input type="checkbox" value="${f}"> ${f}`;
    row.querySelector("input").checked = current.includes(f);
    row.querySelector("input").addEventListener("change", setDirtyTrue);
    flagsBox.appendChild(row);
  }

  const bansBox = $("#srv-bans");
  bansBox.innerHTML = "";
  const groups = [
    ["auto ban report limits", ["censor report limit", "silence report limit", "suspend report limit"]],
    ["server ban durations", ["censor duration", "silence duration", "suspend duration"]],
    ["admin ban durations", ["censor duration", "silence duration", "suspend duration"]],
    ["default ban durations", ["censor duration", "silence duration", "suspend duration"]],
  ];
  for (const [key, fields] of groups) {
    const wrap = document.createElement("div");
    wrap.className = "grid";
    wrap.style.marginBottom = "10px";
    const legend = document.createElement("div");
    legend.className = "hint";
    legend.textContent = key;
    legend.style.margin = "4px 0";
    bansBox.appendChild(legend);
    const obj = gameCfg()[key]?.[0] || {};
    for (const fld of fields) {
      const lab = document.createElement("label");
      lab.textContent = fld;
      const inp = document.createElement("input");
      inp.type = "number";
      inp.value = obj[fld] ?? 0;
      inp.dataset.group = key;
      inp.dataset.field = fld;
      inp.addEventListener("input", setDirtyTrue);
      lab.appendChild(inp);
      wrap.appendChild(lab);
    }
    bansBox.appendChild(wrap);
  }

  $("#srv-name").oninput = setDirtyTrue;
  $("#srv-desc").oninput = setDirtyTrue;
  $("#srv-pass").oninput = setDirtyTrue;
  $("#srv-port").oninput = setDirtyTrue;
  $("#srv-cuplist").oninput = setDirtyTrue;
  $("#srv-countdown").oninput = setDirtyTrue;
  $("#srv-voting").oninput = setDirtyTrue;
}

function setDirtyTrue() { setDirty(true); }

function collectServer() {
  net().name = $("#srv-name").value;
  net().description = $("#srv-desc").value;
  net().password = $("#srv-pass").value;
  net()["game port"] = parseInt($("#srv-port").value, 10) || 30100;
  const g = gameCfg();
  g["cup list"] = $("#srv-cuplist").value;
  g["event loop name"] = $("#srv-loop").value.replace(/\.becl$/, "");
  g["countdown time"] = parseInt($("#srv-countdown").value, 10) || 60000;
  g["voting time"] = parseInt($("#srv-voting").value, 10) || 20000;
  g.flags = $$("#srv-flags input:checked").map((i) => i.value).join(" ");
  for (const inp of $$("#srv-bans input")) {
    const key = inp.dataset.group, fld = inp.dataset.field;
    g[key] = g[key] || [{}];
    g[key][0][fld] = parseInt(inp.value, 10) || 0;
  }
}

$("#save-server").addEventListener("click", async () => {
  try {
    collectServer();
    await api(`/api/config/${scnfName}`, { method: "PUT", body: JSON.stringify({ content: scnf }) });
    setDirty(false);
    status($("#server-status"), "Saved ✓");
  } catch (e) {
    status($("#server-status"), e.message, true);
  }
});

function populateLoopSelect(loopFiles) {
  const sel = $("#srv-loop");
  sel.innerHTML = "";
  for (const f of loopFiles) {
    const opt = document.createElement("option");
    opt.value = f;
    opt.textContent = f;
    sel.appendChild(opt);
  }
  sel.value = gameCfg()["event loop name"]
    ? `${gameCfg()["event loop name"]}.becl`
    : loopFiles[0] || "";
  sel.onchange = setDirtyTrue;
}

/* ---------------- Event loop tab ---------------- */

function populateLoopSelect2(loopFiles) {
  const sel = $("#loop-select");
  sel.innerHTML = "";
  for (const f of loopFiles) {
    const opt = document.createElement("option");
    opt.value = f;
    opt.textContent = f;
    sel.appendChild(opt);
  }
}

async function loadLoop(file) {
  loopName = file;
  loopData = (await api(`/api/config/${file}`)).content;
  if (!Array.isArray(loopData.events)) loopData.events = [];
  $("#loop-select").value = file;
  const active = scnf["game server config"]?.[0]?.["event loop name"];
  const hint = $("#loop-hint");
  if (file.replace(/\.becl$/, "") === active) {
    hint.textContent = `This is the ACTIVE rotation loaded by the server.`;
    hint.classList.add("active-loop");
  } else {
    hint.textContent = `Not the active loop (active: ${active || "none"}). Switch in the Server tab if intended.`;
    hint.classList.remove("active-loop");
  }
  renderEvents();
  setDirty(false);
}

$("#loop-select").addEventListener("change", async (e) => {
  if (dirty && !confirm("Discard unsaved changes?")) { e.target.value = loopName; return; }
  await loadLoop(e.target.value);
});

/* Re-scan config dir and rebuild both loop dropdowns + the cup datalist.
   Keeps the Server tab's current selection if the file still exists. */
async function refreshLoopFiles() {
  configs = await api("/api/configs");
  const loopFiles = configs.filter((c) => c.name.endsWith(".becl")).map((c) => c.name);
  $("#loop-files").innerHTML = loopFiles.map((f) => `<option value="${f.replace(/\.becl$/, "")}">`).join("");
  const srvPrev = $("#srv-loop").value;
  populateLoopSelect(loopFiles);
  if (loopFiles.includes(srvPrev)) $("#srv-loop").value = srvPrev;
  populateLoopSelect2(loopFiles);
  return loopFiles;
}

$("#loop-new").addEventListener("click", async () => {
  if (dirty && !confirm("Discard unsaved changes?")) return;
  let name = prompt("New event loop file name (without .becl):", "");
  if (name === null) return;
  name = name.trim().replace(/\.becl$/i, "").replace(/[^A-Za-z0-9_-]/g, "");
  if (!name) { status($("#loop-status"), "Invalid name — use letters, digits, _ and - only", true); return; }
  const file = `${name}.becl`;
  if (configs.some((c) => c.name === file)) { status($("#loop-status"), `${file} already exists`, true); return; }
  try {
    // Skeleton the game and the editor both accept; user adds events afterwards.
    const skeleton = { bbmeta: "becl v0 n1", events: [defaultEvent()] };
    await api(`/api/config/${file}`, { method: "PUT", body: JSON.stringify({ content: skeleton }) });
    await refreshLoopFiles();
    await loadLoop(file);
    status($("#loop-status"), `Created ${file} ✓`);
  } catch (e) {
    status($("#loop-status"), e.message, true);
  }
});

$("#loop-add").addEventListener("click", () => {
  loopData.events.push(defaultEvent());
  setDirty(true);
  renderEvents();
});$("#loop-save").addEventListener("click", async () => {
  try {
    await api(`/api/config/${loopName}`, { method: "PUT", body: JSON.stringify({ content: loopData }) });
    setDirty(false);
    status($("#loop-status"), "Saved ✓");
  } catch (e) {
    status($("#loop-status"), e.message, true);
  }
});

/* ---------------- Generate loop dialog ---------------- */

const genDialog = $("#gen-dialog");

function genLevels(scope) {
  const withEvents = game.tracks.filter((t) => t.has_event);
  if (scope === "race") return withEvents.filter((t) => !t.default_mode);
  if (scope === "special") return withEvents.filter((t) => t.default_mode);
  return withEvents;
}

function fillGenSelect(sel, items, value) {
  sel.innerHTML = "";
  for (const it of items) {
    const o = document.createElement("option");
    o.value = it.id;
    o.textContent = it.name;
    sel.appendChild(o);
  }
  sel.value = value;
}

$("#loop-generate").addEventListener("click", () => {
  if (dirty && !confirm("Discard unsaved changes?")) return;
  const withEvents = game.tracks.filter((t) => t.has_event);
  $("#gen-count-all").textContent = withEvents.length;
  $("#gen-count-race").textContent = withEvents.filter((t) => !t.default_mode).length;
  $("#gen-count-special").textContent = withEvents.filter((t) => t.default_mode).length;

  fillGenSelect($("#gen-damage"), [{ id: "", name: "(game default)" }, ...game.vehicle_damage_ids.map((d) => ({ id: d.id, name: d.name }))], "");
  fillGenSelect($("#gen-ai"), game.ai_sets.map((a) => ({ id: a.id, name: a.name })), "career/ai-class-all.aist");
  fillGenSelect($("#gen-weather"), [{ id: "", name: "(game default)" }, ...game.weathers.map((w) => ({ id: w.id, name: `${w.name} (${w.stem})` }))], "");

  const modesBox = $("#gen-modes");
  modesBox.innerHTML = "";
  for (const m of game.game_modes) {
    if (!m.id) continue; // empty = native/default handled by the checkbox above
    const row = document.createElement("label");
    row.className = "chkrow";
    row.innerHTML = `<input type="checkbox" value="${m.id}"> ${m.name}`;
    modesBox.appendChild(row);
  }
  syncGenModes();

  status($("#gen-status"), "");
  genDialog.showModal();
});

function syncGenModes() {
  const intrinsic = $("#gen-intrinsic").checked;
  $$("#gen-modes input").forEach((i) => (i.disabled = intrinsic));
  $("#gen-modes").style.opacity = intrinsic ? "0.5" : "1";
}

$("#gen-intrinsic").addEventListener("change", syncGenModes);
$("#gen-cancel").addEventListener("click", () => $("#gen-dialog").close());
$("#gen-create").addEventListener("click", async () => {
  const scope = $('input[name="gen-scope"]:checked').value;
  const levels = genLevels(scope).map((t) => t.id);
  const intrinsic = $("#gen-intrinsic").checked;
  const modes = intrinsic
    ? ["intrinsic"]
    : $$('#gen-modes input[type="checkbox"]:checked').map((i) => i.value);
  if (!modes.length) return status($("#gen-status"), "Select at least one game mode", true);
  const payload = {
    name: $("#gen-name").value.trim(),
    modes,
    level_ids: levels,
    weather: $("#gen-weather").value,
    ai_set: $("#gen-ai").value,
    laps: parseInt($("#gen-laps").value, 10) || 1,
    time_limit: parseInt($("#gen-time").value, 10) || 1,
    teams: parseInt($("#gen-teams").value, 10) || 1,
    max_participants: parseInt($("#gen-parts").value, 10) || 1,
    bot_count: parseInt($("#gen-bots").value, 10) || 0,
    reset_delay: parseInt($("#gen-reset").value, 10) || 0,
    damage: $("#gen-damage").value,
    flags: "",
  };
  try {
    const res = await api("/api/generate-loop", { method: "POST", body: JSON.stringify(payload) });
    genDialog.close();
    await refreshLoopFiles();
    await loadLoop(res.name);
    status($("#loop-status"), `Generated ${res.name} with ${res.events} events ✓`);
  } catch (e) {
    status($("#gen-status"), e.message, true);
  }
});

function defaultEvent() {
  return {
    level: [{ "level id": "track06_1", "weather path": "", "ai set path": "career/ai-class-all.aist", "game mode id": "" }],
    rules: [{ "laps": 5, "time limit": 3, "number of teams": 1, "max number of participants": 24, flags: "", "car reset delay (seconds)": 2, "vehicle damage id": "" }],
    "bot count": 8,
  };
}

function renderEvents() {
  const box = $("#events");
  box.innerHTML = "";
  loopData.events.forEach((ev, idx) => box.appendChild(eventCard(ev, idx)));
}

function eventCard(ev, idx) {
  const tpl = $("#tpl-event").content.cloneNode(true);
  const card = tpl.querySelector(".event");
  const lv = ev.level?.[0] || {};
  const ru = ev.rules?.[0] || {};
  card.dataset.idx = idx;
  card.draggable = true;

  const trackSel = card.querySelector(".ev-track");
  for (const t of game.tracks) {
    const o = document.createElement("option");
    o.value = t.id;
    o.textContent = `${t.display} (${t.id})`;
    trackSel.appendChild(o);
  }
  trackSel.value = lv["level id"] || game.tracks[0]?.id || "";
  if (!trackSel.value) trackSel.value = game.tracks[0]?.id;

  const weatherSel = card.querySelector(".ev-weather");
  fillWeather(weatherSel, trackSel.value, lv["weather path"]);
  trackSel.addEventListener("change", () => {
    lv["level id"] = trackSel.value;
    fillWeather(weatherSel, trackSel.value, "");
    card.querySelector(".event-title").textContent = trackLabel(trackSel.value);
    setDirty(true);
  });

  const aiSel = card.querySelector(".ev-ai");
  for (const a of game.ai_sets) {
    const o = document.createElement("option");
    o.value = a.id;
    o.textContent = a.name + (a.virtual ? "" : "");
    aiSel.appendChild(o);
  }
  // allow a custom value not in the list
  if (lv["ai set path"] && ![...aiSel.options].some((o) => o.value === lv["ai set path"])) {
    const o = document.createElement("option");
    o.value = lv["ai set path"];
    o.textContent = lv["ai set path"];
    aiSel.appendChild(o);
  }
  aiSel.value = lv["ai set path"] || "career/ai-class-all.aist";

  const modeSel = card.querySelector(".ev-mode");
  for (const m of game.game_modes) {
    const o = document.createElement("option");
    o.value = m.id;
    o.textContent = m.name;
    modeSel.appendChild(o);
  }
  modeSel.value = lv["game mode id"] ?? "";

  card.querySelector(".ev-laps").value = ru.laps ?? 3;
  card.querySelector(".ev-time").value = ru["time limit"] ?? 3;
  card.querySelector(".ev-teams").value = ru["number of teams"] ?? 1;
  card.querySelector(".ev-parts").value = ru["max number of participants"] ?? 24;
  card.querySelector(".ev-bots").value = ev["bot count"] ?? 8;
  card.querySelector(".ev-reset").value = ru["car reset delay (seconds)"] ?? 2;

  const dmgSel = card.querySelector(".ev-damage");
  for (const d of game.vehicle_damage_ids) {
    const o = document.createElement("option");
    o.value = d.id;
    o.textContent = d.name;
    dmgSel.appendChild(o);
  }
  dmgSel.value = ru["vehicle damage id"] ?? "";

  const flagsFs = card.querySelector(".ev-flags");
  const curFlags = (ru.flags || "").split(",").map((s) => s.trim()).filter(Boolean);
  for (const f of game.rules_flags) {
    const row = document.createElement("label");
    row.className = "chkrow";
    row.innerHTML = `<input type="checkbox" value="${f}"> ${f}`;
    row.querySelector("input").checked = curFlags.includes(f);
    flagsFs.appendChild(row);
  }

  card.querySelector(".event-title").textContent = trackLabel(trackSel.value);

  // wire input events
  card.addEventListener("input", (e) => {
    const t = e.target;
    if (t === trackSel) return; // handled above
    if (t === weatherSel) lv["weather path"] = t.value;
    else if (t === aiSel) lv["ai set path"] = t.value;
    else if (t === modeSel) lv["game mode id"] = t.value;
    else if (t.classList.contains("ev-laps")) ru.laps = parseInt(t.value, 10) || 1;
    else if (t.classList.contains("ev-time")) ru["time limit"] = parseInt(t.value, 10) || 1;
    else if (t.classList.contains("ev-teams")) ru["number of teams"] = parseInt(t.value, 10) || 1;
    else if (t.classList.contains("ev-parts")) ru["max number of participants"] = parseInt(t.value, 10) || 1;
    else if (t.classList.contains("ev-bots")) ev["bot count"] = parseInt(t.value, 10) || 0;
    else if (t.classList.contains("ev-reset")) ru["car reset delay (seconds)"] = parseInt(t.value, 10) || 0;
    else if (t === dmgSel) ru["vehicle damage id"] = t.value;
    else if (t.type === "checkbox") {
      const vals = $$('input[type="checkbox"]:checked', flagsFs).map((i) => i.value);
      ru.flags = vals.join(" ");
    }
    setDirty(true);
  });

  weatherSel.addEventListener("change", () => { lv["weather path"] = weatherSel.value; setDirty(true); });
  aiSel.addEventListener("change", () => { lv["ai set path"] = aiSel.value; setDirty(true); });
  modeSel.addEventListener("change", () => { lv["game mode id"] = modeSel.value; setDirty(true); });
  dmgSel.addEventListener("change", () => { ru["vehicle damage id"] = dmgSel.value; setDirty(true); });

  card.querySelector(".del").addEventListener("click", () => {
    if (!confirm(`Remove event ${idx + 1} (${trackLabel(lv["level id"])})?`)) return;
    loopData.events.splice(idx, 1);
    setDirty(true);
    renderEvents();
  });
  card.querySelector(".dup").addEventListener("click", () => {
    loopData.events.splice(idx + 1, 0, JSON.parse(JSON.stringify(ev)));
    setDirty(true);
    renderEvents();
  });

  // drag reorder
  card.addEventListener("dragstart", (e) => {
    card.classList.add("dragging");
    e.dataTransfer.setData("text/plain", idx);
    e.dataTransfer.effectAllowed = "move";
  });
  card.addEventListener("dragend", () => card.classList.remove("dragging"));
  card.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; });
  card.addEventListener("drop", (e) => {
    e.preventDefault();
    const from = parseInt(e.dataTransfer.getData("text/plain"), 10);
    if (Number.isNaN(from) || from === idx) return;
    const [moved] = loopData.events.splice(from, 1);
    loopData.events.splice(idx, 0, moved);
    setDirty(true);
    renderEvents();
  });

  return card;
}

function trackLabel(id) {
  const t = game.tracks.find((t) => t.id === id);
  return t ? `${t.display} (${id})` : id;
}

function fillWeather(sel, levelId, current) {
  const track = game.tracks.find((t) => t.id === levelId);
  const allowed = new Set(track?.weathers ?? []);
  sel.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "(game default)";
  sel.appendChild(none);
  for (const w of game.weathers) {
    if (!allowed.has(w.id) && w.stem !== "default") continue;
    const o = document.createElement("option");
    o.value = w.id;
    o.textContent = `${w.name} (${w.stem})`;
    sel.appendChild(o);
  }
  // ensure current value present even if heuristic missed
  if (current && ![...sel.options].some((o) => o.value === current)) {
    const o = document.createElement("option");
    o.value = current;
    o.textContent = current;
    sel.appendChild(o);
  }
  sel.value = current || "";
}

/* ---------------- Cups tab ---------------- */

function renderCups() {
  const box = $("#cups");
  box.innerHTML = "";
  cupsData.cups.forEach((cup, idx) => box.appendChild(cupCard(cup, idx)));
}

function cupCard(cup, idx) {
  const tpl = $("#tpl-cup").content.cloneNode(true);
  const card = tpl.querySelector(".cup");
  card.dataset.idx = idx;
  cup["race settings"] = cup["race settings"] || [{}];
  const rs = cup["race settings"][0];

  card.querySelector(".cup-title").textContent = cup["cup name"] || `Cup ${idx + 1}`;
  card.querySelector(".cup-name").value = cup["cup name"] ?? "";
  card.querySelector(".cup-loop").value = cup["event loop"] ?? "";
  card.querySelector(".cup-desc").value = cup["cup description"] ?? "";
  card.querySelector(".cup-icon").value = cup.icon ?? "";

  const orderSel = card.querySelector(".cup-order");
  for (const o0 of game.start_orders) {
    const o = document.createElement("option");
    o.value = o0;
    o.textContent = o0;
    orderSel.appendChild(o);
  }
  orderSel.value = rs["start order"] || "random";

  card.querySelector(".cup-points").value = rs["point distribution"] ?? "";
  card.querySelector(".cup-bestlap").value = rs["points for best lap time"] ?? 0;
  card.querySelector(".cup-highscore").value = rs["points for highest score"] ?? 0;
  card.querySelector(".cup-multiplier").value = rs["last race multiplier"] ?? 1;

  const flagsFs = card.querySelector(".cup-flags");
  const known = ["no points for bots"];
  const cur = (rs.flags || "").split(",").map((s) => s.trim()).filter(Boolean);
  for (const f of known) {
    const row = document.createElement("label");
    row.className = "chkrow";
    row.innerHTML = `<input type="checkbox" value="${f}"> ${f}`;
    row.querySelector("input").checked = cur.includes(f);
    flagsFs.appendChild(row);
  }
  // free-text flags input for anything exotic
  const extra = document.createElement("label");
  extra.className = "chkrow";
  extra.innerHTML = `other flags <input type="text" class="cup-flags-text" style="flex:1" placeholder="space-separated">`;
  extra.querySelector("input").value = cur.filter((c) => !known.includes(c)).join(" ");
  flagsFs.appendChild(extra);

  const crList = card.querySelector(".cr-list");
  const crCount = card.querySelector(".cr-count");
  cup["car restriction"] = cup["car restriction"] || [];

  function renderCR() {
    crList.innerHTML = "";
    crCount.textContent = cup["car restriction"].length;
    cup["car restriction"].forEach((r, i) => {
      const row = $("#tpl-cr").content.cloneNode(true).querySelector(".cr-row");
      row.querySelector(".cr-type").value = r["allowed car type"] ?? "";
      row.querySelector(".cr-flags").value = r.flags ?? "";
      row.addEventListener("input", (e) => {
        if (e.target.classList.contains("cr-type")) r["allowed car type"] = e.target.value;
        else if (e.target.classList.contains("cr-flags")) r.flags = e.target.value;
        setDirty(true);
      });
      row.querySelector(".cr-del").addEventListener("click", () => {
        cup["car restriction"].splice(i, 1);
        setDirty(true);
        renderCR();
      });
      crList.appendChild(row);
    });
  }
  renderCR();
  card.querySelector(".cr-add").addEventListener("click", () => {
    cup["car restriction"].push({ "allowed car type": "", flags: "" });
    setDirty(true);
    renderCR();
  });

  card.addEventListener("input", (e) => {
    const t = e.target;
    if (t.classList.contains("cup-name")) { cup["cup name"] = t.value; card.querySelector(".cup-title").textContent = t.value || `Cup ${idx + 1}`; }
    else if (t.classList.contains("cup-loop")) cup["event loop"] = t.value;
    else if (t.classList.contains("cup-desc")) cup["cup description"] = t.value;
    else if (t.classList.contains("cup-icon")) cup.icon = t.value;
    else if (t === orderSel) rs["start order"] = t.value;
    else if (t.classList.contains("cup-points")) rs["point distribution"] = t.value;
    else if (t.classList.contains("cup-bestlap")) rs["points for best lap time"] = parseInt(t.value, 10) || 0;
    else if (t.classList.contains("cup-highscore")) rs["points for highest score"] = parseInt(t.value, 10) || 0;
    else if (t.classList.contains("cup-multiplier")) rs["last race multiplier"] = parseFloat(t.value) || 1;
    else if (t.classList.contains("cup-flags-text")) {
      const checks = $$('input[type="checkbox"]:checked', flagsFs).map((i) => i.value);
      rs.flags = [...checks, ...t.value.split(/\s+/).filter(Boolean)].join(" ");
    } else if (t.type === "checkbox") {
      const checks = $$('input[type="checkbox"]:checked', flagsFs).map((i) => i.value);
      const extraTxt = $(".cup-flags-text", flagsFs)?.value.split(/\s+/).filter(Boolean) || [];
      rs.flags = [...checks, ...extraTxt].join(" ");
    }
    setDirty(true);
  });

  card.querySelector(".del").addEventListener("click", () => {
    if (!confirm(`Remove cup "${cup["cup name"] || idx + 1}"?`)) return;
    cupsData.cups.splice(idx, 1);
    setDirty(true);
    renderCups();
  });
  card.querySelector(".dup").addEventListener("click", () => {
    cupsData.cups.splice(idx + 1, 0, JSON.parse(JSON.stringify(cup)));
    setDirty(true);
    renderCups();
  });

  return card;
}

$("#cups-add").addEventListener("click", () => {
  cupsData.cups.push({
    "race settings": [{
      "point distribution": "10;8;6;5;4;3;2;1;0",
      flags: "",
      "start order": "random",
      "points for best lap time": 0,
      "points for highest score": 0,
      "last race multiplier": 1,
    }],
    "event loop": "",
    "cup name": "New Cup",
    "cup description": "",
    icon: "",
    "car restriction": [],
  });
  setDirty(true);
  renderCups();
});

$("#cups-save").addEventListener("click", async () => {
  try {
    await api(`/api/config/${cupsName}`, { method: "PUT", body: JSON.stringify({ content: cupsData }) });
    setDirty(false);
    status($("#cups-status"), "Saved ✓");
  } catch (e) {
    status($("#cups-status"), e.message, true);
  }
});

/* ---------------- Backups tab ---------------- */

async function loadBackups() {
  const rows = await api("/api/backups");
  const tbody = $("#backups-table tbody");
  tbody.innerHTML = "";
  for (const b of rows) {
    const tr = document.createElement("tr");
    const d = new Date(b.mtime * 1000).toLocaleString();
    tr.innerHTML = `<td>${b.name}</td><td>${(b.size / 1024).toFixed(1)} kB</td><td>${d}</td>
      <td><button class="small restore">Restore</button></td>`;
    tr.querySelector(".restore").addEventListener("click", async () => {
      if (!confirm(`Restore ${b.name}? Current file will be backed up first.`)) return;
      try {
        await api("/api/restore", { method: "POST", body: JSON.stringify({ backup: b.name }) });
        alert("Restored. Reload the page to see the restored file.");
        location.reload();
      } catch (e) { alert(e.message); }
    });
    tbody.appendChild(tr);
  }
  if (!rows.length) tbody.innerHTML = `<tr><td colspan="4" class="hint">No backups yet.</td></tr>`;
}
$("#backups-refresh").addEventListener("click", loadBackups);

/* ---------------- Raw tab ---------------- */

async function loadRaw() {
  const sel = $("#raw-select");
  if (!sel.options.length) {
    for (const c of configs) {
      const o = document.createElement("option");
      o.value = c.name;
      o.textContent = c.name;
      sel.appendChild(o);
    }
    sel.value = scnfName;
    sel.addEventListener("change", loadRawContent);
  }
  await loadRawContent();
}

async function loadRawContent() {
  const name = $("#raw-select").value;
  try {
    const data = await api(`/api/config/${name}`);
    $("#raw-text").value = JSON.stringify(data.content, null, 4);
    status($("#raw-status"), "");
  } catch (e) {
    status($("#raw-status"), e.message, true);
  }
}
$("#raw-reload").addEventListener("click", loadRawContent);

$("#raw-save").addEventListener("click", async () => {
  const name = $("#raw-select").value;
  let content;
  try { content = JSON.parse($("#raw-text").value); }
  catch (e) { return status($("#raw-status"), `JSON parse error: ${e.message}`, true); }
  try {
    await api(`/api/config/${name}`, { method: "PUT", body: JSON.stringify({ content }) });
    status($("#raw-status"), "Saved ✓");
    setDirty(false);
    // refresh in-memory copies
    if (name === scnfName) { scnf = content; renderServerTab(); }
    else if (name === loopName) loopData = content;
    else if (name === cupsName) cupsData = content;
  } catch (e) {
    status($("#raw-status"), e.message, true);
  }
});

/* ---------------- go ---------------- */

boot().catch((e) => {
  document.querySelector("main").innerHTML =
    `<div class="card"><h2>Failed to load</h2><p>${e.message}</p></div>`;
});
