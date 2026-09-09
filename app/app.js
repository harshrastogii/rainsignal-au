/* RainSignal — map-first operating instrument.
   Reads the collector's and model's committed outputs. Computes nothing about the
   weather itself; every number here was produced upstream by the frozen pipeline. */
(() => {
"use strict";

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const SVGNS = "http://www.w3.org/2000/svg";
const el = (n, a = {}) => { const e = document.createElementNS(SVGNS, n);
  for (const k in a) e.setAttribute(k, a[k]); return e; };

const RAMP = ["--r0","--r1","--r2","--r3","--r4","--r5"]
  .map(v => getComputedStyle(document.documentElement).getPropertyValue(v).trim());
const UNKNOWN = getComputedStyle(document.documentElement).getPropertyValue("--unknown").trim();

const S = {
  stations:{}, preds:null, latest:null, health:null, trust:null, model:null, geo:null,
  selected:null, mode:"rain", filtered:[], activeIdx:-1,
};

/* ------------------------------------------------------------------ helpers */
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

function rampColor(t){                       // t in 0..1
  if (t == null || Number.isNaN(t)) return UNKNOWN;
  const x = clamp(t, 0, 1) * (RAMP.length - 1);
  const i = Math.floor(x), f = x - i;
  if (i >= RAMP.length - 1) return RAMP[RAMP.length - 1];
  return mix(RAMP[i], RAMP[i + 1], f);
}
function mix(a, b, t){
  const p = h => [1,3,5].map(i => parseInt(h.slice(i, i + 2), 16));
  const [r1,g1,b1] = p(a), [r2,g2,b2] = p(b);
  const c = (x, y) => Math.round(x + (y - x) * t);
  return `rgb(${c(r1,r2)},${c(g1,g2)},${c(b1,b2)})`;
}

const pct = v => v == null ? "—" : `${Math.round(v * 100)}%`;
const fmtNum = (v, d = 1) => v == null ? "—" : Number(v).toFixed(d);
const pretty = name => name.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/RAAF/, "RAAF");

const DAY = 86400000;
function isoDate(s){ const d = new Date(s + "T00:00:00"); return Number.isNaN(+d) ? null : d; }
function todayLocal(){ const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); }
function daysBetween(a, b){ return Math.round((b - a) / DAY); }
function longDate(d){
  return d.toLocaleDateString("en-AU", { weekday:"long", day:"numeric", month:"long" });
}
function relativeDay(target){
  const t = todayLocal(), diff = daysBetween(t, target);
  if (diff === 0) return "today";
  if (diff === 1) return "tomorrow";
  if (diff === -1) return "yesterday";
  return diff < 0 ? `${-diff} days ago` : `in ${diff} days`;
}
function ago(iso){
  const then = new Date(iso), mins = Math.round((Date.now() - then) / 60000);
  if (!Number.isFinite(mins)) return "unknown";
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.round(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

/* Plain-language reading of a probability. The number stays visible beside it;
   this sentence is what someone actually acts on. */
function saying(p){
  if (p == null) return "We could not produce a number here.";
  if (p < 0.10) return "Rain is very unlikely.";
  if (p < 0.25) return "Rain is unlikely.";
  if (p < 0.45) return "Rain is possible, but more likely not.";
  if (p < 0.60) return "It could go either way.";
  if (p < 0.80) return "Rain is likely.";
  return "Rain is very likely.";
}
function trustVerdict(f1){
  if (f1 == null) return { label:"Not measured", tone:"none" };
  if (f1 >= 0.70) return { label:"Strong here", tone:"good" };
  if (f1 >= 0.60) return { label:"Good here",   tone:"good" };
  if (f1 >= 0.50) return { label:"Mixed here",  tone:"mid"  };
  return { label:"Weak here", tone:"low" };
}

const ICON = {
  back:'<path d="M15 5l-7 7 7 7"/>',
  warn:'<path d="M12 8.5v4.2"/><path d="M12 16.3h.01"/><path d="M10.3 4.2 3.4 16.5a2 2 0 0 0 1.7 3h13.8a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z"/>',
  info:'<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
};
const icon = (n, cls = "") =>
  `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICON[n]}</svg>`;

/* -------------------------------------------------------------------- data */
async function grab(path){
  try {
    const r = await fetch(path, { cache:"no-store" });
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch { return null; }
}

async function load(){
  const [stations, preds, latest, health, trust, model] = await Promise.all([
    grab("data/stations.json"), grab("data/predictions.json"), grab("data/latest.json"),
    grab("data/health.json"),   grab("data/station_reliability.json"),
    grab("data/model.json"),
  ]);
  if (!stations) { fail("Could not load the station list."); return false; }
  S.stations = Object.fromEntries(Object.entries(stations).filter(([, v]) => v.collectable));
  S.preds = preds; S.latest = latest; S.health = health;
  S.trust = trust; S.model = model;
  return true;
}

function fail(msg){
  const f = $("#freshness"); f.dataset.state = "error";
  $("#freshness-text").textContent = msg;
  $("#national-sub").textContent =
    "The live data could not be loaded. The map and readout need the collector's output.";
}

/* ------------------------------------------------------------------ values */
const predFor  = n => S.preds?.predictions?.[n]?.rain_probability ?? null;
const heldFor  = n => S.preds?.withheld?.[n] ?? null;
const trustFor = n => S.trust?.stations?.[n] ?? null;
const obsFor   = n => S.latest?.observations?.[n] ?? null;

/* ------------------------------------------------------------------- map */
const MAPTILER_KEY = "WBLnSvimIk9ssjlbmo5X";
const STYLE = `https://api.maptiler.com/maps/dataviz-light/style.json?key=${MAPTILER_KEY}`;
const AU_BOUNDS = [[110.0, -44.5], [155.5, -9.5]];   // mainland + Tasmania

// Capitals and the well-known towns claim a map label before their neighbours do.
// MapLibre resolves label collisions natively; sort-key decides who wins one.
const PRIORITY = { Melbourne:0, Sydney:0, Brisbane:0, Perth:0, Adelaide:0, Hobart:0,
  Darwin:0, Canberra:0, Cairns:1, AliceSprings:1, Townsville:1, GoldCoast:1,
  Launceston:1, Woomera:1, NorfolkIsland:1, Albany:2, Newcastle:2, Mildura:2 };

let map = null, mapReady = false;

function stationsGeoJSON(){
  return {
    type:"FeatureCollection",
    features: Object.entries(S.stations).map(([name, st]) => {
      const p = predFor(name), t = trustFor(name);
      return {
        type:"Feature",
        id: hashId(name),
        geometry:{ type:"Point", coordinates:[st.lon, st.lat] },
        properties:{
          name, label: pretty(name),
          prob: p == null ? -1 : p,
          trust: t ? clamp((t.f1 - 0.35) / 0.45, 0, 1) : -1,
          sort: PRIORITY[name] ?? 5,
        },
      };
    }),
  };
}
const idMap = new Map();
function hashId(name){
  if (!idMap.has(name)) idMap.set(name, idMap.size + 1);
  return idMap.get(name);
}
const nameById = id => [...idMap.entries()].find(([, v]) => v === id)?.[0] ?? null;

// One ramp expression, reused by both modes. -1 means "no value" and paints hollow.
function rampExpr(prop){
  const stops = [];
  RAMP.forEach((c, i) => { stops.push(i / (RAMP.length - 1), c); });
  return ["case", ["<", ["get", prop], 0], "#ffffff",
          ["interpolate", ["linear"], ["get", prop], ...stops]];
}

function initMap(){
  map = new maplibregl.Map({
    container:"map", style:STYLE, bounds:AU_BOUNDS,
    fitBoundsOptions:{ padding:mapPadding() },
    minZoom:2.6, maxZoom:11, attributionControl:{ compact:true },
    dragRotate:false, pitchWithRotate:false, touchZoomRotate:true,
  });
  map.touchZoomRotate.disableRotation();
  map.on("load", () => {
    map.addSource("stations", { type:"geojson", data:stationsGeoJSON(), promoteId:undefined });

    // A soft halo so a dark dot never sits directly on light cartography.
    map.addLayer({ id:"station-halo", type:"circle", source:"stations",
      paint:{
        "circle-radius":["interpolate",["linear"],["zoom"],3,9,6,15,10,22],
        "circle-color":"#ffffff",
        "circle-opacity":["case",["boolean",["feature-state","selected"],false],.95,.55],
        "circle-blur":.35,
      }});

    map.addLayer({ id:"station-dot", type:"circle", source:"stations",
      paint:{
        "circle-radius":["interpolate",["linear"],["zoom"],
          3,["case",["boolean",["feature-state","selected"],false],7.5,5],
          6,["case",["boolean",["feature-state","selected"],false],11,8],
          10,["case",["boolean",["feature-state","selected"],false],16,12]],
        "circle-color":rampExpr("prob"),
        "circle-stroke-width":["case",["boolean",["feature-state","selected"],false],2.5,1.25],
        "circle-stroke-color":["case",
          ["boolean",["feature-state","selected"],false],"#0e7c86",
          ["<",["get","prob"],0],"#b6c2cd","rgba(16,28,40,.38)"],
        "circle-opacity":["case",["<",["get","prob"],0],.9,1],
        // transitions make mode switches and selection feel continuous
        "circle-radius-transition":{ duration:260, delay:0 },
        "circle-color-transition":{ duration:260, delay:0 },
      }});

    map.addLayer({ id:"station-label", type:"symbol", source:"stations",
      layout:{
        "text-field":["get","label"],
        "text-font":["Inter Regular","Noto Sans Regular"],
        "text-size":["interpolate",["linear"],["zoom"],3,11,7,13],
        "text-offset":[0,1.1], "text-anchor":"top",
        "text-allow-overlap":false, "text-ignore-placement":false,
        "text-optional":true,
        "symbol-sort-key":["get","sort"],       // capitals place first
        "text-padding":3,
      },
      paint:{
        "text-color":"#334656",
        "text-halo-color":"rgba(255,255,255,.92)",
        "text-halo-width":1.6,
      }});

    mapReady = true;
    paintMap();
    wireMap();
  });
  map.on("error", e => {
    if (String(e?.error?.message || "").includes("Failed to fetch")) return;
  });
}

function mapPadding(){
  const wide = innerWidth > 900;
  return wide
    ? { top:70, right:parseInt(getComputedStyle(document.documentElement)
        .getPropertyValue("--panel-w")) + 50, bottom:60, left:60 }
    : { top:70, right:40, bottom:Math.round(innerHeight * 0.52) + 40, left:40 };
}

function wireMap(){
  const hit = ["station-dot","station-halo"];
  let hoveredId = null;

  map.on("mousemove", "station-dot", e => {
    map.getCanvas().style.cursor = "pointer";
    const f = e.features[0]; if (!f) return;
    if (hoveredId !== null && hoveredId !== f.id)
      map.setFeatureState({ source:"stations", id:hoveredId }, { hover:false });
    hoveredId = f.id;
    map.setFeatureState({ source:"stations", id:f.id }, { hover:true });
    showTipAt(e.originalEvent.clientX, e.originalEvent.clientY, f.properties.name);
  });
  map.on("mouseleave", "station-dot", () => {
    map.getCanvas().style.cursor = "";
    if (hoveredId !== null) map.setFeatureState({ source:"stations", id:hoveredId }, { hover:false });
    hoveredId = null; hideTip();
  });
  map.on("click", "station-dot", e => { if (e.features[0]) select(e.features[0].properties.name); });
  map.on("click", e => {
    const f = map.queryRenderedFeatures(e.point, { layers:hit });
    if (!f.length && S.selected) deselect();
  });

  $("#zoom-in").addEventListener("click", () => map.zoomIn({ duration:260 }));
  $("#zoom-out").addEventListener("click", () => map.zoomOut({ duration:260 }));
  $("#zoom-reset").addEventListener("click", () =>
    map.fitBounds(AU_BOUNDS, { padding:mapPadding(), duration:600 }));
}

function paintMap(){
  if (!mapReady) return;
  const prop = S.mode === "rain" ? "prob" : "trust";
  map.setPaintProperty("station-dot", "circle-color", rampExpr(prop));
  map.setPaintProperty("station-dot", "circle-stroke-color", ["case",
    ["boolean",["feature-state","selected"],false],"#0e7c86",
    ["<",["get",prop],0],"#b6c2cd","rgba(16,28,40,.38)"]);
  map.setPaintProperty("station-dot", "circle-opacity",
    ["case",["<",["get",prop],0],.9,1]);
}

let selectedId = null;
function markSelected(name){
  if (!mapReady) return;
  if (selectedId !== null) map.setFeatureState({ source:"stations", id:selectedId }, { selected:false });
  selectedId = name ? hashId(name) : null;
  if (selectedId !== null) map.setFeatureState({ source:"stations", id:selectedId }, { selected:true });
}

function flyTo(name){
  if (!mapReady || !name) return;
  const st = S.stations[name]; if (!st) return;
  // Ease toward the town without diving in: the national picture stays legible.
  map.easeTo({ center:[st.lon, st.lat], zoom:Math.max(map.getZoom(), 5.4),
               padding:mapPadding(), duration:700, easing:t => 1 - Math.pow(1 - t, 3) });
}

/* ----------------------------------------------------------------- tooltip */
const tip = $("#tooltip");
function showTipAt(x, y, name){
  tip.innerHTML = `<b>${pretty(name)}</b> &nbsp;<span>${labelFor(name)}</span>`;
  tip.hidden = false;
  place(x, y);
}
const showTip = (e, name) => showTipAt(e.clientX, e.clientY, name);
const moveTip = e => place(e.clientX, e.clientY);
function place(x, y){
  const r = tip.getBoundingClientRect();
  tip.style.left = `${clamp(x - r.width / 2, 8, innerWidth - r.width - 8)}px`;
  tip.style.top  = `${Math.max(8, y - r.height - 12)}px`;
}
const hideTip = () => { tip.hidden = true; };

/* ------------------------------------------------------------------ legend */
function paintLegend(){
  const rain = S.mode === "rain";
  const target = S.preds?.target_date ? isoDate(S.preds.target_date) : null;
  const when = target ? (relativeDay(target) === "tomorrow" ? " tomorrow" : ` on ${longDate(target)}`) : "";
  $("#legend-title").textContent = rain ? `Chance of rain${when}` : "How reliable the estimate is here";
  $("#legend-ramp").style.background = `linear-gradient(90deg, ${RAMP.join(",")})`;
  $("#legend-lo").textContent = rain ? "0%" : "Weakest";
  $("#legend-hi").textContent = rain ? "100%" : "Strongest";
  $("#legend-note").textContent = rain
    ? "Hollow means we did not have enough measurements to give a number."
    : "Measured on years of past days the model never saw while learning.";
}

/* ---------------------------------------------------------------- national */
function paintNational(){
  const p = S.preds;
  if (!p){ $("#national-sub").textContent = "No estimates are available right now."; return; }

  const target = isoDate(p.target_date);
  const rel = target ? relativeDay(target) : "";
  const n = p.stations_predicted, held = p.stations_withheld;

  const vals = Object.values(p.predictions || {}).map(v => v.rain_probability);
  const wettest = Object.entries(p.predictions || {})
    .sort((a, b) => b[1].rain_probability - a[1].rain_probability)[0];

  $("#lede").textContent = target && relativeDay(target) === "tomorrow"
    ? "Will it rain tomorrow?"
    : `Rain on ${target ? longDate(target) : "the target day"}`;

  let s = `Estimates for <strong>${n} of ${n + held} towns</strong>`;
  if (target) s += `, for <strong>${longDate(target)}</strong> (${rel})`;
  s += ".";
  if (wettest) s += ` Highest right now is <strong>${pretty(wettest[0])}</strong> at ${pct(wettest[1].rain_probability)}.`;
  s += " Pick a town to see what its number is built from.";
  $("#national-sub").innerHTML = s;
}

/* -------------------------------------------------------------- freshness */
function paintFreshness(){
  const f = $("#freshness"), t = $("#freshness-text");
  const p = S.preds, h = S.health;
  if (!p){ f.dataset.state = "error"; t.textContent = "No estimates loaded"; return; }

  const target = isoDate(p.target_date);
  const behind = target ? daysBetween(target, todayLocal()) : null;
  const obsAge = h?.run_utc ? ago(h.run_utc) : null;

  if (behind != null && behind > 0){
    f.dataset.state = "stale";
    t.textContent = `Estimate is ${behind} day${behind === 1 ? "" : "s"} out of date. It was for ${longDate(target)}`;
  } else {
    f.dataset.state = "fresh";
    t.textContent = obsAge ? `Observations updated ${obsAge}` : "Up to date";
  }
  f.title = `Observations collected ${h?.run_utc ?? "unknown"} · estimate generated ${p.generated_utc}`;
}

/* ------------------------------------------------------------------ search */
function stationList(){
  return Object.keys(S.stations).sort((a, b) => {
    const pa = predFor(a), pb = predFor(b);
    if (pa == null && pb == null) return a.localeCompare(b);
    if (pa == null) return 1;
    if (pb == null) return -1;
    return pb - pa;
  });
}
function paintResults(q = ""){
  const list = $("#results");
  const needle = q.trim().toLowerCase().replace(/\s+/g, "");
  S.filtered = stationList().filter(n => !needle || n.toLowerCase().includes(needle));
  S.activeIdx = -1;
  list.textContent = "";

  if (!S.filtered.length){
    const li = document.createElement("li");
    li.className = "results-empty";
    li.textContent = `No town matches “${q.trim()}”.`;
    list.appendChild(li);
    $("#search").setAttribute("aria-expanded", "false");
    return;
  }
  $("#search").setAttribute("aria-expanded", "true");

  S.filtered.forEach(name => {
    const p = predFor(name);
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button"; b.className = "res"; b.dataset.name = name;
    b.setAttribute("role", "option"); b.setAttribute("aria-selected", "false");
    b.innerHTML =
      `<span class="res-swatch" style="background:${p == null ? UNKNOWN : rampColor(p)}"></span>` +
      `<span class="res-name">${pretty(name)}</span>` +
      `<span class="res-val"${p == null ? ' data-none="true"' : ""}>${p == null ? "no estimate" : pct(p)}</span>`;
    b.addEventListener("click", () => select(name));
    li.appendChild(b); list.appendChild(li);
  });
}
function moveActive(step){
  const items = $$(".res");
  if (!items.length) return;
  S.activeIdx = (S.activeIdx + step + items.length) % items.length;
  items.forEach((b, i) => {
    const on = i === S.activeIdx;
    b.dataset.active = String(on);
    b.setAttribute("aria-selected", String(on));
    if (on) b.scrollIntoView({ block:"nearest" });
  });
}

/* ------------------------------------------------------------ the readout */
function select(name, push = true){
  if (!S.stations[name]) return;
  S.selected = name;
  if (push && location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  markSelected(name);
  flyTo(name);
  hideTip();
  $("#pane-national").hidden = true;
  const pane = $("#pane-station");
  pane.hidden = false;
  pane.innerHTML = readout(name);
  pane.dataset.entering = "true";
  requestAnimationFrame(() => requestAnimationFrame(() => { pane.dataset.entering = "false"; }));
  $("#panel-scroll").scrollTop = 0;
  const fill = pane.querySelector(".answer-fill");
  if (fill){ fill.style.setProperty("--fill", "0");
    requestAnimationFrame(() => requestAnimationFrame(() => fill.style.setProperty("--fill", "1"))); }
  $("#back")?.addEventListener("click", deselect);
  pane.querySelector(".back")?.focus({ preventScroll:true });
}
function deselect(){
  S.selected = null;
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  markSelected(null);
  $("#pane-station").hidden = true;
  $("#pane-national").hidden = false;
  $("#search").focus({ preventScroll:true });
}

function readout(name){
  const p = predFor(name), held = heldFor(name), t = trustFor(name);
  const o = obsFor(name), st = S.stations[name];
  const rec = S.preds?.predictions?.[name];
  const target = S.preds?.target_date ? isoDate(S.preds.target_date) : null;
  const obsDate = S.preds?.observation_date ? isoDate(S.preds.observation_date) : null;
  const v = trustVerdict(t?.f1);

  /* the answer, or an honest account of why there isn't one */
  let answer;
  if (p != null){
    answer = `
      <div class="answer">
        <p class="answer-label">Chance of rain ${target ? `on ${longDate(target)}` : ""}</p>
        <div class="answer-figure">
          <span class="answer-num" style="color:${rampColor(p)}">${Math.round(p * 100)}</span>
          <span class="answer-unit">out of 100</span>
        </div>
        <div class="answer-bar">
          <div class="answer-fill" style="width:${clamp(p * 100, 2, 100)}%;background:${rampColor(p)}"></div>
        </div>
        <p class="answer-say">${saying(p)}</p>
        <p class="answer-note">“Rain” means more than 1&nbsp;mm falling over the day.</p>
      </div>`;
  } else {
    const miss = held?.missing ?? [];
    answer = `
      <div class="answer">
        <p class="answer-label">Chance of rain</p>
        <div class="answer-figure"><span class="answer-num" style="color:var(--ink-3)">—</span></div>
        <p class="answer-say">No estimate for this town right now.</p>
        <p class="answer-note">${miss.length
          ? `The station did not report ${miss.length} measurement${miss.length === 1 ? "" : "s"} the model needs. Rather than guess them, we leave the number out.`
          : "Not enough measurements arrived to build a complete day."}</p>
      </div>`;
  }

  /* what it was built from */
  const obsRow = (label, val, unit = "") =>
    `<div><dt>${label}</dt><dd>${val == null ? "—" : val}${unit ? ` <small>${unit}</small>` : ""}</dd></div>`;
  const built = o ? `
    <div class="block">
      <h2>What this is built from</h2>
      <p class="why">Measurements recorded at this station${obsDate ? ` on <strong>${longDate(obsDate)}</strong>` : ""}.
      These are observations: weather that already happened, not a prediction.</p>
      <dl class="obs">
        ${obsRow("Coldest", fmtNum(o.MinTemp), "°C")}
        ${obsRow("Warmest", fmtNum(o.MaxTemp), "°C")}
        ${obsRow("Rain that day", fmtNum(o.Rainfall), "mm")}
        ${obsRow("Strongest gust", o.WindGustSpeed == null ? null : `${fmtNum(o.WindGustSpeed, 0)}`, "km/h")}
      </dl>
      <p class="answer-note" style="margin-top:10px">Last reading ${o.age_min != null ? `${o.age_min} min ago` : "unknown"}
      · ${st?.bom_name ?? ""}</p>
    </div>` : "";

  /* how much to trust it here -- the finding that a national figure hides */
  const catchRate = t?.recall != null ? Math.round(t.recall * 10) : null;
  const trust = t ? `
    <div class="block">
      <h2>How reliable is this here?</h2>
      <p class="why">We checked this town against years of days the model had never seen.
      Reliability is not the same everywhere.</p>
      <div class="trust-head">
        <span class="trust-verdict" style="color:${v.tone === "good" ? "var(--accent)" : v.tone === "mid" ? "var(--warn)" : "var(--bad)"}">${v.label}</span>
        <span class="res-val">${t.n_test_days.toLocaleString()} days checked</span>
      </div>
      <div class="trust-scale">
        <div class="trust-track"></div>
        <div class="trust-pin" style="left:${clamp((t.f1 - 0.35) / 0.45 * 100, 2, 98)}%"></div>
      </div>
      <div class="trust-ends"><span>Weakest town</span><span>Strongest town</span></div>
      ${catchRate != null ? `
        <div class="catch" aria-hidden="true">
          ${Array.from({ length:10 }, (_, i) => `<span class="pip" data-on="${i < catchRate}"></span>`).join("")}
        </div>
        <p class="catch-say">Of every 10 days it rained here, the model spotted about
        <strong>${catchRate}</strong> of them in advance.</p>` : ""}
      ${t.rain_rate < 0.15 ? `
        <div class="flag">${icon("info")}<span>Rain is rare here: only ${pct(t.rain_rate)} of days.
        Models find rare events harder, which is why this town scores below the wet coast.</span></div>` : ""}
    </div>` : "";

  /* imputation disclosure, only when it happened */
  const imputed = rec?.imputed_by_frozen_pipeline;
  const gapFlag = imputed?.length ? `
    <div class="flag">${icon("warn")}<span>${imputed.length} measurement${imputed.length === 1 ? " was" : "s were"}
    missing (${imputed.join(", ")}). The model filled ${imputed.length === 1 ? "it" : "them"} using the same
    rule it learned during training. The number still shows, but it rests on less evidence.</span></div>` : "";

  /* technical detail, available but never leading */
  const m = S.model;
  const tech = `
    <details>
      <summary>Technical detail</summary>
      <div class="tech">
        <table>
          <tbody>
            ${t ? `
            <tr><th>F1 at this station</th><td>${fmtNum(t.f1, 3)}</td></tr>
            <tr><th>Precision / recall</th><td>${fmtNum(t.precision, 3)} / ${fmtNum(t.recall, 3)}</td></tr>
            <tr><th>ROC-AUC</th><td>${fmtNum(t.roc_auc, 3)}</td></tr>
            <tr><th>Rain days in test set</th><td>${pct(t.rain_rate)}</td></tr>` : ""}
            ${m ? `
            <tr><th>Model</th><td>${m.primary_model}</td></tr>
            <tr><th>National F1 / ROC-AUC</th><td>${fmtNum(m.test_metrics?.[m.primary_model]?.f1, 4)} / ${fmtNum(m.test_metrics?.[m.primary_model]?.roc_auc, 4)}</td></tr>` : ""}
            ${rec ? `
            <tr><th>Inputs present</th><td>${rec.inputs_present} / ${rec.inputs_total}</td></tr>
            <tr><th>9am reading offset</th><td>${rec.provenance?.["9am"]?.offset_min ?? "—"} min</td></tr>
            <tr><th>3pm reading offset</th><td>${rec.provenance?.["3pm"]?.offset_min ?? "—"} min</td></tr>` : ""}
          </tbody>
        </table>
        <p>A neural network trained on 187,121 historical station-days and frozen before
        this site existed. It reports a probability rather than a yes or no, because the best
        cut-off sits near 0.31 rather than 0.5. Publishing a label would hide that choice.</p>
      </div>
    </details>`;

  return `
    <button type="button" class="back" id="back">${icon("back")}All towns</button>
    <h1 class="place">${pretty(name)}</h1>
    <p class="place-sub">${st?.state ?? ""} · ${st?.lat?.toFixed(2)}°, ${st?.lon?.toFixed(2)}°</p>
    ${answer}${gapFlag}${built}${trust}${tech}`;
}

/* ------------------------------------------------------------------- wire */
function setMode(mode){
  S.mode = mode;
  $("#mode-rain").setAttribute("aria-pressed", String(mode === "rain"));
  $("#mode-trust").setAttribute("aria-pressed", String(mode === "trust"));
  paintMap(); paintLegend();
}

function wire(){
  $("#mode-rain").addEventListener("click", () => setMode("rain"));
  $("#mode-trust").addEventListener("click", () => setMode("trust"));

  const search = $("#search"), clear = $("#search-clear");
  search.addEventListener("input", () => {
    clear.hidden = !search.value;
    paintResults(search.value);
  });
  search.addEventListener("keydown", e => {
    if (e.key === "ArrowDown"){ e.preventDefault(); moveActive(1); }
    else if (e.key === "ArrowUp"){ e.preventDefault(); moveActive(-1); }
    else if (e.key === "Enter"){
      const items = $$(".res");
      const pick = S.activeIdx >= 0 ? items[S.activeIdx] : items[0];
      if (pick){ e.preventDefault(); select(pick.dataset.name); }
    } else if (e.key === "Escape" && search.value){ search.value = ""; clear.hidden = true; paintResults(); }
  });
  clear.addEventListener("click", () => {
    search.value = ""; clear.hidden = true; paintResults(); search.focus();
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && S.selected) deselect();
  });

  let t = null;
  addEventListener("resize", () => {
    clearTimeout(t);
    t = setTimeout(() => { if (mapReady) map.resize(); }, 140);
  });
}

/* ------------------------------------------------------------------- boot */
(async () => {
  wire();
  const ok = await load();
  if (!ok) return;
  paintFreshness(); paintNational(); paintLegend(); paintResults();
  initMap();

  const want = decodeURIComponent(location.hash.replace(/^#/, ""));
  if (want && S.stations[want]) select(want, false);
  addEventListener("hashchange", () => {
    const n = decodeURIComponent(location.hash.replace(/^#/, ""));
    if (n && S.stations[n]) select(n, false); else if (!n && S.selected) deselect();
  });
})();

})();
