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
  gauge:'<path d="M5 17a8 8 0 1 1 14 0"/><path d="m12 14 4-4"/>',
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

    // Dataviz Light renders sea and land within a few percent of each other, which
    // is right for a neutral overlay and wrong for a weather map. A cool tint on the
    // water gives the coastline back without competing with the station colours.
    try {
      map.setPaintProperty("Water", "fill-color", "#d9e7ef");
      map.setPaintProperty("Water shadow", "fill-color", "#c6d8e3");
      map.setPaintProperty("Background", "background-color", "#f4f6f8");
      map.setPaintProperty("Ocean labels", "text-color", "#8ba7b8");
    } catch { /* a style revision may rename these; the map still works untinted */ }

    mapReady = true;
    paintMap();
    wireMap();
    // A deep link resolves before the style finishes loading, so the selection made
    // then has to be replayed here or the town is never marked on the map.
    if (S.selected){ markSelected(S.selected); flyTo(S.selected); }
  });
  map.on("error", e => {
    if (String(e?.error?.message || "").includes("Failed to fetch")) return;
  });
}

/* Desktop keeps the panel inset because the readout genuinely covers the map there.
   On mobile nothing overlays the map, so both jobs want the same plain inset. */
function mapPadding(){          // fitting all of Australia
  if (innerWidth > 900){
    return { top:70, right:parseInt(getComputedStyle(document.documentElement)
      .getPropertyValue("--panel-w")) + 50, bottom:60, left:60 };
  }
  // The map is its own block now, with the controls beneath it, so a plain inset is
  // all it needs.
  return { top:18, right:18, bottom:18, left:18 };
}

function flyPadding(){          // centring one town
  if (innerWidth > 900) return mapPadding();
  return { top:22, right:22, bottom:22, left:22 };
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

  // Reset returns the whole view to how it opened: all of Australia, nothing selected.
  $("#zoom-reset").addEventListener("click", () => {
    if (S.selected) deselect();
    map.fitBounds(AU_BOUNDS, { padding:mapPadding(), duration:600 });
  });

  $("#locate").addEventListener("click", locate);
}

/* Find the nearest station to the visitor. RainSignal only knows 44 places, so this
   answers "which of them is yours" rather than pretending to forecast a exact spot. */
function locate(){
  const btn = $("#locate");
  if (!navigator.geolocation){
    say("This browser will not share a location.");
    return;
  }
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  navigator.geolocation.getCurrentPosition(pos => {
    btn.disabled = false; btn.removeAttribute("aria-busy");
    const { latitude:lat, longitude:lon } = pos.coords;
    let best = null, bestKm = Infinity;
    for (const [name, st] of Object.entries(S.stations)){
      const d = haversine(lat, lon, st.lat, st.lon);
      if (d < bestKm){ best = name; bestKm = d; }
    }
    if (!best){ say("No station could be matched to your location."); return; }
    select(best);
    say(`Nearest station: ${pretty(best)}, about ${Math.round(bestKm)} km away.`, 4000);
  }, err => {
    btn.disabled = false; btn.removeAttribute("aria-busy");
    say(err.code === err.PERMISSION_DENIED
      ? "Location permission was declined."
      : "Your location could not be read.");
  }, { enableHighAccuracy:false, timeout:10000, maximumAge:300000 });
}

function haversine(la1, lo1, la2, lo2){
  const R = 6371, rad = d => d * Math.PI / 180;
  const dLa = rad(la2 - la1), dLo = rad(lo2 - lo1);
  const a = Math.sin(dLa/2)**2 + Math.cos(rad(la1)) * Math.cos(rad(la2)) * Math.sin(dLo/2)**2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

/* A brief message in the tooltip slot, which already announces politely. */
let sayTimer = null;
function say(msg, ms = 3200){
  const t = $("#tooltip");
  t.innerHTML = msg;
  t.hidden = false;
  t.style.left = "50%"; t.style.top = "auto";
  t.style.bottom = "24px"; t.style.transform = "translateX(-50%)";
  clearTimeout(sayTimer);
  sayTimer = setTimeout(() => {
    t.hidden = true; t.style.bottom = ""; t.style.transform = "";
  }, ms);
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
               padding:flyPadding(), duration:700, easing:t => 1 - Math.pow(1 - t, 3) });
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
  $("#legend-title").textContent = rain ? "Chance of rain" : "How reliable it has been";
  $("#legend-ramp").style.background = `linear-gradient(90deg, ${RAMP.join(",")})`;
  $("#legend-lo").textContent = rain ? "0%" : "Weakest";
  $("#legend-hi").textContent = rain ? "100%" : "Strongest";
  const when = target
    ? (relativeDay(target) === "tomorrow" ? "for tomorrow" : `for ${longDate(target)}`)
    : "";
  $("#legend-note").textContent = rain
    ? `${when}. A hollow ring means no estimate today.`.replace(/^\. /, "")
    : "Past record at each town, not today's estimate.";
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
    const d = target.toLocaleDateString("en-AU", { day:"numeric", month:"short" });
    t.textContent = `${behind} day${behind === 1 ? "" : "s"} behind · last estimate ${d}`;
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
  // On a phone the readout lives below the map, so scroll it into view rather than
  // leaving the visitor looking at a map that silently changed.
  if (innerWidth <= 900){
    const p = $("#panel"), host = $("#pane-map");
    if (p && host) host.scrollTo({ top:Math.max(p.offsetTop - 8, 0),
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }
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
    const pretty_miss = {
      Temp9am:"9am temperature", Temp3pm:"3pm temperature",
      Humidity9am:"9am humidity", Humidity3pm:"3pm humidity",
      Pressure9am:"9am air pressure", Pressure3pm:"3pm air pressure",
      WindSpeed9am:"9am wind speed", WindSpeed3pm:"3pm wind speed",
      WindDir9am:"9am wind direction", WindDir3pm:"3pm wind direction",
      MinTemp:"the day's low", MaxTemp:"the day's high",
      Rainfall:"rain measured that day", RainToday:"whether it rained that day",
      WindGustSpeed:"strongest gust", WindGustDir:"gust direction",
      TempRange:"temperature range", PressureChange:"pressure change",
      HumidityChange:"humidity change",
    };
    const readable = [...new Set(miss.map(m => pretty_miss[m] ?? m))].slice(0, 6);
    answer = `
      <div class="answer">
        <p class="answer-label">Chance of rain${target ? ` on ${longDate(target)}` : ""}</p>
        <div class="answer-figure">
          <span class="answer-num" style="color:var(--ink-3)">—</span>
          <span class="answer-unit">no estimate</span>
        </div>
        <div class="nonum">
          ${icon("info")}
          <div>
            <p><b>Why there is no number here.</b> RainSignal only gives a chance when the
            weather station sent every measurement the model needs for a full day. This
            station missed ${miss.length === 1 ? "one of them" : `${miss.length} of them`}.</p>
            ${readable.length ? `<ul class="missing-list">${
              readable.map(r => `<li>${r}</li>`).join("")}</ul>` : ""}
            <p>We would rather show nothing than fill the gaps with guesses and hand you a
            number that looks just as confident as a real one.</p>
          </div>
        </div>
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

  /* How much to trust it here. This is a claim about the model's past record at this
     station, not about today. When there is no estimate the block is stood down and
     says so plainly, because "Strong here" beside a missing number read as though a
     prediction existed. */
  const catchRate = t?.recall != null ? Math.round(t.recall * 10) : null;
  const hasNow = p != null;
  const trust = t ? `
    <div class="block" data-muted="${!hasNow}">
      <h2>How well has this worked here before?</h2>
      <p class="why">${hasNow
        ? `A track record for ${pretty(name)}, measured over years of past days the model
           had never seen. It describes the model's history here, not today's number.`
        : `There is no estimate for ${pretty(name)} today, so nothing below applies to
           right now. It is the model's past record here, kept for context.`}</p>
      <div class="trust-head">
        <span class="trust-verdict" style="color:${hasNow
          ? (v.tone === "good" ? "var(--accent)" : v.tone === "mid" ? "var(--warn)" : "var(--bad)")
          : "var(--ink-3)"}">${v.label}${hasNow ? "" : " (past record only)"}</span>
        <span class="res-val">${t.n_test_days.toLocaleString()} past days</span>
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
        <p class="catch-say">On past days when it rained here, the model had spotted about
        <strong>${catchRate} in 10</strong> of them the day before.</p>` : ""}
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


/* ===================================================================== */
/* Analytics: the same findings, told for someone who has never met a model */
/* ===================================================================== */
const REPO = "https://github.com/harshrastogii/rainsignal-au";

function pctOf(x){ return Math.round(x * 100); }

function barChart(rows, opts = {}){
  if (innerWidth < 620) return barChartNarrow(rows);
  const w = 660, rowH = 46, pad = { l:150, r:56, t:6, b:22 };
  const h = pad.t + rows.length * rowH + pad.b;
  const iw = w - pad.l - pad.r;
  const max = opts.max ?? 100;
  const ticks = [0, 25, 50, 75, 100];
  const parts = [];
  ticks.forEach(t => {
    const x = pad.l + (t / max) * iw;
    parts.push(`<line class="ax-line" x1="${x}" x2="${x}" y1="${pad.t}" y2="${pad.t + rows.length * rowH - 12}"/>`);
    parts.push(`<text class="ax-txt" x="${x}" y="${h - 6}" text-anchor="middle">${t}</text>`);
  });
  rows.forEach((r, i) => {
    const y = pad.t + i * rowH;
    parts.push(`<text class="bar-name" x="${pad.l - 12}" y="${y + 15}" text-anchor="end">${r.name}</text>`);
    r.bars.forEach((b, j) => {
      const bw = Math.max((b.value / max) * iw, 2), by = y + 4 + j * 13;
      parts.push(`<rect x="${pad.l}" y="${by}" width="${bw}" height="10" rx="3" fill="${b.color}"${
        b.dim ? ' opacity=".55"' : ""}/>`);
      parts.push(`<text class="bar-val" x="${pad.l + bw + 7}" y="${by + 9}">${b.label}</text>`);
    });
  });
  return `<div class="chart"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${opts.alt || ""}">${parts.join("")}</svg></div>`;
}

function barChartNarrow(rows){
  // Drawn as HTML rather than SVG. Text in a 340-unit viewBox came out around 7px on a
  // phone, and short labels inside the bars were unreadable. Plain elements wrap, scale
  // with the reader's text size, and let each bar carry a sentence instead of a code.
  return `<div class="mbars">${rows.map(r => `
    <div class="mbar">
      <b>${r.name}</b>
      ${r.bars.map(b => `
        <p>${b.say}</p>
        <span class="mbar-track"><i style="width:${Math.max(b.value, 2)}%;background:${b.color}${
          b.dim ? ";opacity:.55" : ""}"></i></span>`).join("")}
    </div>`).join("")}</div>`;
}

function scatterReliability(){
  const st = S.trust?.stations; if (!st) return "";
  const narrow = innerWidth < 620;
  const w = narrow ? 340 : 660, h = narrow ? 250 : 300;
  const pad = narrow ? { l:34, r:10, t:10, b:40 } : { l:48, r:18, t:12, b:44 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const pts = Object.entries(st);
  const X = v => pad.l + ((v - 0.03) / (0.37 - 0.03)) * iw;
  const Y = v => pad.t + ih - ((v - 0.35) / (0.82 - 0.35)) * ih;
  const parts = [];
  [0.4, 0.5, 0.6, 0.7, 0.8].forEach(v => {
    parts.push(`<line class="ax-line" x1="${pad.l}" x2="${pad.l + iw}" y1="${Y(v)}" y2="${Y(v)}"/>`);
  });
  (narrow ? [0.1, 0.2, 0.3] : [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35]).forEach(v => {
    parts.push(`<text class="ax-txt" x="${X(v)}" y="${h - 22}" text-anchor="middle">${pctOf(v)}%</text>`);
  });
  parts.push(`<text class="ax-txt" x="${pad.l + iw / 2}" y="${h - 6}" text-anchor="middle">how often it rains in that town</text>`);
  parts.push(`<text class="ax-txt" x="${narrow ? 11 : 14}" y="${pad.t + ih / 2}" text-anchor="middle" transform="rotate(-90 ${narrow ? 11 : 14} ${pad.t + ih / 2})">${
    narrow ? "how well it worked" : "how well it worked"}</text>`);
  pts.forEach(([name, v]) => {
    const dry = v.rain_rate < 0.15;
    parts.push(`<circle cx="${X(v.rain_rate).toFixed(1)}" cy="${Y(v.f1).toFixed(1)}" r="${narrow ? 4.5 : 5}"
      fill="${dry ? "var(--warn)" : "var(--r3)"}" opacity=".8" stroke="#fff" stroke-width="1.5"><title>${pretty(name)}</title></circle>`);
  });
  const worst = S.trust.worst, best = S.trust.best;
  const wS = st[worst.station], bS = st[best.station];
  parts.push(`<text class="bar-val" x="${X(wS.rain_rate) + 9}" y="${Y(wS.f1) + 4}">${pretty(worst.station)}</text>`);
  parts.push(`<text class="bar-val" x="${X(bS.rain_rate) - 9}" y="${Y(bS.f1) + 4}" text-anchor="end">${pretty(best.station)}</text>`);
  return `<div class="chart"><svg viewBox="0 0 ${w} ${h}" role="img"
    aria-label="Each of 49 towns plotted by how often it rains there against how well the model worked there.">${parts.join("")}</svg></div>
    <div class="chart-key"><span><i style="background:var(--warn)"></i>rain falls on fewer than 15% of days</span>
    <span><i style="background:var(--r3)"></i>wetter towns</span></div>`;
}

function buildStory(){
  const m = S.model, tr = S.trust;
  if (!m || !tr){ $("#story").innerHTML = "<p>The results could not be loaded.</p>"; return; }
  const T = m.test_metrics, best = m.primary_model;
  const order = ["Neural Network", "Random Forest", "Decision Tree", "Naive Bayes"];
  const NICE = { "Neural Network":"Neural network", "Random Forest":"Random forest",
                 "Decision Tree":"Decision tree", "Naive Bayes":"Naive Bayes" };
  const rainDays = 22;

  const catchRows = order.filter(k => T[k]).map(k => ({
    name: NICE[k],
    bars: [
      { value: pctOf(T[k].recall), label: `caught ${pctOf(T[k].recall)} of 100`,
        say: `Spotted ${pctOf(T[k].recall)} of every 100 rainy days`,
        color:"var(--r4)" },
      { value: pctOf(T[k].precision), label: `right ${pctOf(T[k].precision)}% of the time`,
        say: `When it did warn of rain, it was right ${pctOf(T[k].precision)}% of the time`,
        color:"var(--r2)", dim:true },
    ],
  }));

  const nat = tr.national, worst = tr.worst, best_s = tr.best;
  const catch10 = Math.round(T[best].recall * 10);

  $("#story").innerHTML = `
    <h1>Can a computer tell you if it will rain tomorrow?</h1>
    <p class="standfirst">We gave four different programs eighteen years of Australian
    weather, ${m.training_rows.toLocaleString()} days of it, and asked each one to predict
    the next day's rain. Then we tested them on ${m.test_rows.toLocaleString()} days they
    had never seen.</p>

    <h2>Rain is rare</h2>
    <p>Across the 44 towns RainSignal watches, rain falls on about
    <strong>${rainDays} days in every 100</strong>.</p>
    <div class="dots-100" aria-hidden="true">${(() => {
      // 22 of 100, spread by a fixed offset so the grid reads as a proportion
      // rather than as a stripe. Deterministic, so it never differs between loads.
      const on = new Set();
      let k = 3;
      while (on.size < rainDays){ on.add(k % 100); k += 9; }
      return Array.from({ length:100 }, (_, i) => `<i data-on="${on.has(i)}"></i>`).join("");
    })()}</div>
    <p>That imbalance is the whole difficulty. A program that simply says "no rain" every
    single day is right ${100 - rainDays}% of the time and completely useless. So high
    accuracy on its own proves nothing, and we never judged these programs by it.</p>

    <h2>What we measured</h2>
    <p>Two things matter, and getting better at one usually costs the other. <strong>How
    many rainy days did it spot?</strong> And <strong>when it warned of rain, how often was
    it right?</strong> A program that warns every day spots everything and is almost always
    wrong; one that never warns is never wrong and never useful.</p>
    ${barChart(catchRows, { alt:"Rainy days caught and how often each program was right." })}
    <div class="chart-key">
      <span><i style="background:var(--r4)"></i>rainy days it spotted</span>
      <span><i style="background:var(--r2);opacity:.55"></i>how often it was right to warn</span>
    </div>
    <p class="caption">Naive Bayes spots the most rain, but it warns so often that barely
    half its warnings are right. The neural network warns less and is right far more often
    when it does.</p>

    <h2>The most complicated one won, barely</h2>
    <div class="stat-line">
      <span class="stat-num">${catch10} in 10</span>
      <span class="stat-say">rainy days spotted a day ahead by the program RainSignal
      uses, the ${NICE[best].toLowerCase()}</span>
    </div>
    <p>It came first on every measure we tried. But its lead over the much simpler
    <strong>random forest</strong> was about seven days in every thousand. That is a real
    improvement and a small one, and the simpler method would have got you most of the way
    for a fraction of the effort.</p>

    <h2>It works far better in some towns than others</h2>
    <p>A single national figure hides this completely. Each dot below is one town.</p>
    ${scatterReliability()}
    <p class="caption">The drier the town, the worse the prediction. In
    <strong>${pretty(worst.station)}</strong> the model is at its weakest; in
    <strong>${pretty(best_s.station)}</strong>, on the wet south-west coast, it is at its
    strongest. Rare events are harder to learn, because there are fewer examples
    of them to learn from.</p>

    <h2>What to take from this</h2>
    <ul class="takeaways">
      <li><b>Ask what a number would be for doing nothing.</b>
        <span>Saying "no rain" every day scores ${100 - rainDays}%. Any accuracy figure
        needs that comparison beside it.</span></li>
      <li><b>Ask what it gets wrong, not just how often.</b>
        <span>Missing a storm and falsely predicting one are different failures with
        different costs, and every program here quietly chose between them.</span></li>
      <li><b>A prediction is only as good as the place it is made.</b>
        <span>The same model ranges from genuinely useful on the coast to barely better
        than knowing the local climate inland.</span></li>
      <li><b>The fanciest method won by very little.</b>
        <span>More complexity bought a small gain here, at much greater cost and with no
        ability to explain itself.</span></li>
    </ul>

    <hr>
    <details>
      <summary>Technical detail</summary>
      <div class="tech">
        <table>
          <thead><tr><th>Model</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>ROC-AUC</th></tr></thead>
          <tbody>${order.filter(k => T[k]).map(k => `<tr>
            <th>${NICE[k]}</th>
            <td>${fmtNum(T[k].accuracy, 4)}</td><td>${fmtNum(T[k].precision, 4)}</td>
            <td>${fmtNum(T[k].recall, 4)}</td><td>${fmtNum(T[k].f1, 4)}</td>
            <td>${fmtNum(T[k].roc_auc, 4)}</td></tr>`).join("")}
          </tbody>
        </table>
        <p>Held-out test set of ${m.test_rows.toLocaleString()} station-days, 22.0% positive
        class, never seen during training. Hyperparameters were selected on a validation
        split carved from the training data; the test set was opened once.</p>
        <p>Per-station reliability is F1 measured on the same split:
        ${worst.station} ${fmtNum(worst.f1, 3)} to ${best_s.station} ${fmtNum(best_s.f1, 3)},
        correlating ${fmtNum(tr.rain_rate_f1_correlation, 3)} with local rain frequency.
        National F1 ${fmtNum(nat.f1, 4)}, ROC-AUC ${fmtNum(nat.roc_auc, 4)}.</p>
        <p>The ${NICE[best].toLowerCase()} is served because it scored best and was best
        calibrated (expected calibration error 0.0120), which is what makes it defensible
        to publish its output as a probability rather than a yes or no. Its best decision
        threshold sits near 0.31, not 0.5, so no label is imposed.</p>
        <p>Every figure here is produced by the notebook in
        <a href="how-it-works">
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 1.4A5.6 5.6 0 1 1 8 13.6 5.6 5.6 0 0 1 8 2.4Zm0 2a2.1 2.1 0 0 0-2.1 2.1h1.4a.7.7 0 1 1 1.4 0c0 .5-.2.7-.6 1-.5.4-.8.8-.8 1.6h1.4c0-.4.2-.6.6-.9.5-.4.9-.9.9-1.7A2.1 2.1 0 0 0 8 4.4Zm-.7 6.1v1.4h1.4v-1.4Z"/></svg>
        How RainSignal works
      </a>
      <a href="${REPO}" target="_blank" rel="noopener">the project repository</a> and can
        be reproduced from it.</p>
      </div>
    </details>`;
}

/* ------------------------------------------------------------------ views */
function setView(v){
  const isMap = v === "map";
  $("#view-map").setAttribute("aria-pressed", String(isMap));
  $("#view-analytics").setAttribute("aria-pressed", String(!isMap));
  $("#pane-map").hidden = !isMap;
  $("#pane-analytics").hidden = isMap;
  if (!isMap && !$("#story").dataset.built){
    buildStory(); $("#story").dataset.built = "1";
  }
  if (isMap && mapReady) requestAnimationFrame(() => map.resize());
}

function paintFooter(){
  $("#panel-foot").innerHTML = `
    <p>Observations come from the <strong>Bureau of Meteorology</strong>. The chance shown
    is produced by a student machine-learning model and is <strong>not a Bureau
    forecast</strong>. For official forecasts and warnings go to
    <a href="https://www.bom.gov.au" target="_blank" rel="noopener">bom.gov.au</a>.</p>
    <p class="foot-links">
      <a href="how-it-works">
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 1.4A5.6 5.6 0 1 1 8 13.6 5.6 5.6 0 0 1 8 2.4Zm0 2a2.1 2.1 0 0 0-2.1 2.1h1.4a.7.7 0 1 1 1.4 0c0 .5-.2.7-.6 1-.5.4-.8.8-.8 1.6h1.4c0-.4.2-.6.6-.9.5-.4.9-.9.9-1.7A2.1 2.1 0 0 0 8 4.4Zm-.7 6.1v1.4h1.4v-1.4Z"/></svg>
        How RainSignal works
      </a>
      <a href="${REPO}" target="_blank" rel="noopener">
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38l-.01-1.49c-2.01.37-2.53-.49-2.7-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48l-.01 2.19c0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>
        View the project on GitHub
      </a>
    </p>`;
}

/* ------------------------------------------------------------------- wire */
function setMode(mode){
  S.mode = mode;
  $("#mode-rain").setAttribute("aria-pressed", String(mode === "rain"));
  $("#mode-trust").setAttribute("aria-pressed", String(mode === "trust"));
  paintMap(); paintLegend();
}

function wire(){
  $("#view-map").addEventListener("click", () => setView("map"));
  $("#view-analytics").addEventListener("click", () => setView("analytics"));
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
  let wasNarrow = innerWidth < 620;
  addEventListener("resize", () => {
    clearTimeout(t);
    t = setTimeout(() => {
      if (mapReady) map.resize();
      // the charts are drawn at one of two geometries; rebuild if we crossed over
      const now = innerWidth < 620;
      if (now !== wasNarrow && $("#story").dataset.built){
        wasNarrow = now; buildStory();
      }
    }, 160);
  });
}

/* ------------------------------------------------------------------- boot */
(async () => {
  wire();
  const ok = await load();
  if (!ok) return;
  paintFreshness(); paintNational(); paintLegend(); paintResults(); paintFooter();
  initMap();

  // ?view=analytics lets the How-it-works page link straight to the Analytics view
  if (new URLSearchParams(location.search).get("view") === "analytics") setView("analytics");

  const want = decodeURIComponent(location.hash.replace(/^#/, ""));
  if (want && S.stations[want]) select(want, false);
  addEventListener("hashchange", () => {
    const n = decodeURIComponent(location.hash.replace(/^#/, ""));
    if (n && S.stations[n]) select(n, false); else if (!n && S.selected) deselect();
  });
})();

})();
