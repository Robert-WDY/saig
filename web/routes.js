"use strict";

const get = id => document.getElementById(id);
const base = [30.573, 114.298];
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const map = L.map("route-map", {preferCanvas: true, scrollWheelZoom: false, minZoom: 7, maxZoom: 18}).setView(base, 12);
map.attributionControl.setPrefix(false);
const localMap = L.imageOverlay("/web/wuhan-schematic.png", [[30.39,114.13],[30.72,114.55]],
  {attribution:"武汉本地路线示意 · 河流 Natural Earth", interactive:false}).addTo(map);
const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 18
});
L.control.layers({"本地位置示意":localMap,"在线街道图":tiles}, {}, {collapsed:true}).addTo(map);
const mapElement = get("route-map");
tiles.on("loading", () => { mapElement.dataset.tiles = "loading"; });
tiles.on("tileerror", () => {
  get("tile-feedback").hidden = false;
  if (map.hasLayer(tiles)) { map.removeLayer(tiles); localMap.addTo(map); }
});
tiles.on("load", () => {
  mapElement.dataset.tiles = "settled";
  if (mapElement.querySelector(".leaflet-tile-loaded")) get("tile-feedback").hidden = true;
});
const routeLayer = L.layerGroup().addTo(map);
const playedLayer = L.layerGroup().addTo(map);

const params = new URLSearchParams(location.search);
const selector = get("route-plan");
const play = get("play-route");
const fit = get("fit-route");
const progress = get("route-progress");
const plans = readPlans();
const modeNames = {walk: "步行", metro: "地铁", transit: "公交", taxi: "打车", estimate: "估算转场"};
let points = {};
let day = "";
let rows = [];
let timer = null;

function readPlans() {
  try {
    const state = JSON.parse(sessionStorage.getItem("saig-visitor-workspace-v1"));
    return (state?.plans || []).filter(plan => Object.keys(plan.cards || {}).length);
  } catch {
    return [];
  }
}

function elem(tag, text, name) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (name) node.className = name;
  return node;
}

function external(label, href) {
  const link = elem("a", label + " ↗");
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function coordinates(name) {
  if (!Object.prototype.hasOwnProperty.call(points, name)) return null;
  const point = points[name];
  return Number.isFinite(point.lat) && Number.isFinite(point.lon) ? [point.lat, point.lon] : null;
}

function mapSearch(name) {
  const query = new URLSearchParams({keyword: name, city: "武汉", view: "map"});
  return "https://uri.amap.com/search?" + query;
}

function legNavigation(leg, from, to) {
  const engine = leg?.mode === "walk" ? "fossgis_osrm_foot" : leg?.mode === "taxi" ? "fossgis_osrm_car" : null;
  if (!engine || !from || !to) return null;
  const query = new URLSearchParams({engine, route: from.join(",") + ";" + to.join(",")});
  return "https://www.openstreetmap.org/directions?" + query;
}

function buildStops(card) {
  const stops = card.audit?.stops || [];
  const legs = card.audit?.legs || [];
  const contract = card.contract || {};
  const result = [];
  if (contract.origin && contract.origin !== stops[0]?.place) {
    result.push({name: contract.origin, time: routeTime.exact(contract.start) + " 出发"});
  }
  for (const stop of stops) {
    result.push({name: stop.place, time: routeTime.stop(stop, contract),
      exactTime: routeTime.exact(stop.start) + "–" + routeTime.exact(stop.end)});
  }
  if (contract.destination && contract.destination !== result[result.length - 1]?.name) {
    const deadline = contract.end - (contract.buffer || 0);
    result.push({name: contract.destination,
      time: "预计 " + routeTime.arrival(card.audit?.arrival, deadline) + " 到 · 最晚 " + routeTime.exact(deadline),
      exactTime: routeTime.exact(card.audit?.arrival)});
  }
  return result.map((stop, index) => ({
    ...stop, coords: coordinates(stop.name),
    leg: legs.find(leg => leg.origin === result[index - 1]?.name && leg.destination === stop.name)
  }));
}

function updateDayButtons(plan) {
  const buttons = Object.keys(plan.cards).map(n => {
    const button = elem("button", "第 " + n + " 天", "text-button");
    button.type = "button";
    button.setAttribute("aria-pressed", n === day);
    button.addEventListener("click", () => {
      day = n;
      renderRoute(plan);
      Array.from(get("route-days").children).find(item => item.textContent === button.textContent)?.focus();
    });
    return button;
  });
  get("route-days").replaceChildren(...buttons);
}

function fitRoute() {
  const known = rows.filter(row => row.coords).map(row => row.coords);
  if (known.length) map.fitBounds(known, {padding: [46, 46], maxZoom: 15, animate: false});
}

function active(index, focusMarker = false) {
  rows.forEach((row, position) => {
    const on = position === index;
    row.item.classList.toggle("active", on);
    row.marker?.getElement()?.classList.toggle("active", on);
    row.button.setAttribute("aria-pressed", on);
  });
  const row = rows[index];
  if (!row) return;
  progress.textContent = row.name + "（" + (index + 1) + "/" + rows.length + "）";
  if (focusMarker && row.marker) row.marker.openPopup();
}

function drawRoute(layer, count, style) {
  for (let index = 1; index < count; index += 1) {
    const a = rows[index - 1].coords;
    const b = rows[index].coords;
    if (a && b) L.polyline([a, b], {...style, interactive: false}).addTo(layer);
  }
}

function stopPlayback() {
  if (timer !== null) clearTimeout(timer);
  timer = null;
  play.textContent = "播放路线";
}

function playRoute() {
  if (timer !== null) {
    stopPlayback();
    return;
  }
  if (!rows.some(row => row.coords)) return;
  map.closePopup();
  fitRoute();
  play.textContent = "暂停播放";
  let index = 0;
  function step() {
    playedLayer.clearLayers();
    drawRoute(playedLayer, index + 1, {color: "#ec582e", weight: 6, opacity: .95});
    active(index);
    if (++index < rows.length) timer = setTimeout(step, motion.matches ? 350 : 820);
    else {
      stopPlayback();
      progress.textContent = "路线播放完成";
    }
  }
  step();
}

function renderRoute(plan) {
  stopPlayback();
  map.closePopup();
  routeLayer.clearLayers();
  playedLayer.clearLayers();
  updateDayButtons(plan);
  const card = plan.cards[day];
  rows = buildStops(card);
  get("day-title").textContent = "第 " + day + " 天路线";
  const count = rows.filter(row => row.coords).length;
  get("day-summary").textContent = count + " / " + rows.length + " 个站点已定位";
  const list = get("route-stops");
  const children = [];
  for (const [index, row] of rows.entries()) {
    row.item = elem("li", "", "route-stop");
    const content = elem("span");
    content.append(elem("strong", row.name), elem("span", row.time, "route-stop-time"));
    if (row.exactTime) content.title = "计划原值 " + row.exactTime;
    const button = elem("button", "", "route-stop-main");
    button.type = "button";
    button.disabled = !row.coords;
    button.setAttribute("aria-pressed", "false");
    button.append(elem("span", String(index + 1), "route-stop-index"), content);
    row.button = button;
    const actions = elem("div", "", "route-stop-actions");
    if (row.leg) actions.append(elem("span", [modeNames[row.leg.mode], routeTime.duration(row.leg.minutes)].filter(Boolean).join(" · ")));
    if (!row.coords) actions.append(elem("span", "坐标待核"));
    else if (points[row.name].usage) actions.append(elem("span", points[row.name].usage));
    const link = legNavigation(row.leg, rows[index - 1]?.coords, row.coords);
    if (link) actions.append(external("本段导航", link));
    actions.append(external("在地图中搜索", mapSearch(row.name)));
    row.item.append(button, actions);
    children.push(row.item);
    if (!row.coords) continue;
    const marker = L.marker(row.coords, {
      title: row.name, alt: row.name,
      icon: L.divIcon({className: "map-pin", html: String(index + 1), iconSize: [28, 28], iconAnchor: [14, 14]})
    }).addTo(routeLayer);
    const popup = elem("div");
    popup.append(elem("strong", points[row.name].label || row.name), elem("p", row.time), external("查看地点", mapSearch(row.name)));
    marker.bindPopup(popup).on("click", () => { stopPlayback(); active(index); });
    row.marker = marker;
    button.addEventListener("click", () => { stopPlayback(); active(index, true); });
  }
  list.replaceChildren(...children);
  drawRoute(routeLayer, rows.length, {color: "#12399d", weight: 4, dashArray: "7 8", opacity: .8});
  play.disabled = count < 2;
  fit.disabled = !count;
  progress.textContent = count ? "" : "本日地点坐标待核实";
  fitRoute();
}

function selectPlan(preferredDay) {
  const plan = plans.find(item => item.id === selector.value);
  day = Object.prototype.hasOwnProperty.call(plan.cards, preferredDay) ? preferredDay : Object.keys(plan.cards)[0];
  renderRoute(plan);
}

async function start() {
  if (!plans.length) {
    get("route-stops-header")?.setAttribute("hidden", "");
    return;
  }
  get("route-empty").hidden = true;
  for (const plan of plans) {
    const option = elem("option", plan.title);
    option.value = plan.id;
    selector.append(option);
  }
  if (plans.some(plan => plan.id === params.get("plan"))) selector.value = params.get("plan");
  try {
    const response = await fetch("/route-points");
    if (!response.ok) throw new Error("coordinate load failed");
    points = await response.json();
  } catch {
    get("map-source-note").textContent = "暂时无法读取坐标，可以继续看站点和搜索地点。";
  }
  selector.disabled = false;
  selector.addEventListener("change", () => selectPlan(""));
  selectPlan(params.get("day") || "");
}

fit.addEventListener("click", () => { stopPlayback(); fitRoute(); });
play.addEventListener("click", playRoute);
start();
