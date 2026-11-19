"use strict";

const get = id => document.getElementById(id);
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const map = WuhanMap.create("route-map");
const regionBounds = WuhanMap.bounds;
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

let catalog = [];
const added = new Set();
const removed = new Set();
let requestId = null;
let saving = false;

const nearbyLayer = L.layerGroup().addTo(map);

function stageAddition(name) {
  if (saving || !selected() || added.has(name)) return;
  added.add(name);
  requestId = null;
  get("edit-feedback").textContent = "";
  if (expanded()) toggleExpanded();
  map.closePopup();
  renderEditor(selected());
}

function drawLocalPlaces() {
  nearbyLayer.clearLayers();
  const occupied = [];
  const zoom = map.getZoom();
  const bounds = map.getBounds();
  const plan = selected();
  const card = plan?.cards[day];
  const activeNames = new Set(rows.map(row => row.name));
  const localNames = Object.entries(points).filter(([name,p]) => !activeNames.has(name) && Number.isFinite(p.lat) && Number.isFinite(p.lon));
  const labels = [
    ...rows.filter(row => row.coords).map(row => [row.name, row.coords, "visit"]),
    ...[["汉口",[30.61,114.25]],["汉阳",[30.535,114.22]],["武昌",[30.535,114.345]]].map(([name,pos])=>[name,pos,"district"]),
    ...(zoom >= 11 ? localNames.map(([name,p])=>[name,[p.lat,p.lon],"place"]) : [])
  ];
  for (const [name,coords,kind] of labels) {
    if (!bounds.contains(coords)) continue;
    const pt = map.latLngToContainerPoint(coords);
    const width = name.length * (kind === "district" ? 19 : 13) + 12;
    const gap = kind === "visit" ? 16 : 2;
    const offset = pt.x + gap + width > map.getSize().x ? -width-gap : gap;
    const x = pt.x + offset;
    if (occupied.some(r => x < r.right+4 && x+width > r.left-4 && Math.abs(pt.y-r.y)<20)) continue;
    occupied.push({left:x,right:x+width,y:pt.y});
    const label = elem("span", name, "geo-name "+kind);
    const marker=L.marker(coords,{icon:L.divIcon({className:"geo-label",html:label,iconSize:[width,24],
      iconAnchor:[-offset,12]}),interactive:kind==="place",keyboard:kind==="place",
      title:name,zIndexOffset:-500}).addTo(nearbyLayer);
    if (kind==="place") marker.bindPopup(() => {
      const popup=elem("div");
      popup.append(elem("strong",name));
      if (card && catalog.includes(name) && !card.contract.exclude.includes(name)) {
        const add=elem("button","添加到第 "+day+" 天","text-button");
        add.type="button"; add.disabled=saving || added.has(name);
        add.addEventListener("click",()=>stageAddition(name)); popup.append(add);
      } else popup.append(external("查看地点",mapSearch(name)));
      return popup;
    });
  }
}
map.on("moveend", drawLocalPlaces);
map.on("resize", event => {
  if (event.oldSize.x !== event.newSize.x && rows.length) fitRoute();
});

function expanded() {
  return document.body.classList.contains("map-expanded");
}
function toggleExpanded() {
  const on = !expanded();
  document.body.classList.toggle("map-expanded", on);
  const btn = get("expand-map");
  btn.textContent = on ? "收起大图" : "展开大图";
  btn.setAttribute("aria-pressed", String(on));
  const center = map.getCenter(), zoom = map.getZoom();
  requestAnimationFrame(() => {
    // Keep the visitor's current view; only the container size changes.
    map.invalidateSize({pan: false});
    map.setView(center, zoom, {animate: false});
    btn.focus();
  });
}

get("expand-map").addEventListener("click", toggleExpanded);
document.addEventListener("keydown", e => { if (expanded() && e.key === "Escape") toggleExpanded(); });
get("city-view").addEventListener("click", () => {
  stopPlayback();
  map.fitBounds(regionBounds, {padding:[12,12],animate:false});
});

function renderEditor(plan) {
  get("route-editor").hidden = false;
  const card = plan.cards[day];
  const dirty = added.size + removed.size > 0;
  selector.disabled = saving || dirty;
  for (const btn of get("route-days").children) btn.disabled = saving || dirty;
  const picker = get("place-picker");
  const previous = picker.value;
  const choices = catalog.filter(n => !card.order.includes(n) && !added.has(n) &&
    !card.contract.exclude.includes(n) && ![card.contract.origin,card.contract.destination].includes(n));
  picker.replaceChildren(new Option("选择景点、街区或美食地点", ""), ...choices.map(n => new Option(n,n)));
  if (choices.includes(previous)) picker.value = previous;
  picker.disabled = saving || !choices.length;
  get("add-stop").disabled = saving || !picker.value;
  const summary = [];
  if (added.size) summary.push("将添加：" + Array.from(added).join("、"));
  if (removed.size) summary.push("将移除：" + Array.from(removed).join("、"));
  get("draft-stops").textContent = summary.join("；");
  get("edit-actions").hidden = !dirty;
  get("discard-stops").disabled = saving;
  get("apply-stops").disabled = saving;
  get("apply-stops").textContent = saving ? "正在重排…" : "应用并重排行程";
}

function selected() { return plans.find(p => p.id === selector.value); }

get("place-picker").addEventListener("change", () => { get("add-stop").disabled = saving || !get("place-picker").value; });
get("add-stop").addEventListener("click", () => {
  if (saving || !get("place-picker").value) return;
  stageAddition(get("place-picker").value);
});
get("discard-stops").addEventListener("click", () => {
  if (saving) return;
  added.clear(); removed.clear(); requestId = null;
  get("edit-feedback").textContent = "";
  renderRoute(selected(), false);
});

get("apply-stops").addEventListener("click", async () => {
  if (saving || !(added.size || removed.size)) return;
  const plan = selected();
  const card = plan.cards[day];
  const dayKey = day;
  saving = true;
  requestId = requestId || newId();
  renderRoute(plan, false);
  try {
    const key = "saig-visitor-workspace-v1";
    const workspace = JSON.parse(sessionStorage.getItem(key));
    if (!workspace?.session) throw new Error("本页会话已关闭，请回接待台重新打开。");
    const response = await fetch("/route-edit", {method:"POST", headers:apiHeaders(),
      body:JSON.stringify({session:workspace.session,request_id:requestId,change:{
        plan:plan.id,day:dayKey,basis:{order:card.order,contract:card.contract},
        add:Array.from(added),remove:Array.from(removed)
      }})});
    const updated = await response.json();
    if (!response.ok) throw new Error(updated.error || "重排未完成，原行程已保留。");
    const replacement = saveMapResult(workspace, updated, dayKey);
    Object.assign(plan,replacement);
    if (plan.id === "current") {
      const stale = plans.findIndex(p => p.id === "preview");
      if (stale >= 0) { plans.splice(stale,1); selector.querySelector('option[value="preview"]')?.remove(); }
    }
    added.clear(); removed.clear(); requestId = null;
    get("edit-feedback").textContent = "第 " + dayKey + " 天已重排。"+routeTime.change(card,updated.cards[dayKey])+"。";
  } catch (error) {
    get("edit-feedback").textContent = error.message || "未收到服务器确认，可点击重试。";
  } finally {
    saving = false;
    renderRoute(plan);
  }
});

window.addEventListener("pageshow", e => { if (e.persisted) location.reload(); });

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
  return WuhanMap.stops(card,points);
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

function renderRoute(plan, refit = true) {
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
    const anchored = row.name === card.contract.origin || row.name === card.contract.destination;
    const editable = card.order.includes(row.name) && !anchored;
    function removeButton() {
      const control = elem("button", removed.has(row.name) ? "保留此站" : "移除" + (card.contract.must.includes(row.name) ? "必去站" : "此站"), "stop-edit");
      control.type = "button";
      control.setAttribute("aria-label", control.textContent + " · " + row.name);
      control.disabled = saving;
      control.addEventListener("click", () => {
        if (saving) return;
        removed.has(row.name) ? removed.delete(row.name) : removed.add(row.name);
        if (expanded()) toggleExpanded();
        requestId = null;
        get("edit-feedback").textContent = "";
        renderRoute(plan, false);
        get("apply-stops").focus();
      });
      return control;
    }
    if (editable) actions.append(removeButton());
    else if (anchored) actions.append(elem("span","行程锚点"));
    row.item.classList.toggle("staged", removed.has(row.name));
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
    if (editable) popup.append(removeButton());
    marker.bindPopup(popup).on("click", () => { stopPlayback(); active(index); });
    row.marker = marker;
    button.addEventListener("click", () => { stopPlayback(); active(index, true); });
  }
  list.replaceChildren(...children);
  drawRoute(routeLayer, rows.length, {color: "#12399d", weight: 4, dashArray: "7 8", opacity: .8});
  play.disabled = count < 2;
  fit.disabled = !count;
  progress.textContent = count ? "" : "本日地点坐标待核实";
  const url="/routes?" + new URLSearchParams({plan:plan.id,day});
  if (location.pathname+location.search !== url) history.replaceState(null,"",url);
  document.querySelector(".nav-map").href=url;
  try {
    const key="saig-visitor-workspace-v1";
    const workspace=JSON.parse(sessionStorage.getItem(key));
    if (workspace && (workspace.mapSelection?.plan !== plan.id || workspace.mapSelection?.day !== day)) {
      workspace.mapSelection={plan:plan.id,day};
      sessionStorage.setItem(key,JSON.stringify(workspace));
    }
  } catch { /* Selection is still available in the page URL. */ }
  renderEditor(plan);
  if (refit) fitRoute();
  drawLocalPlaces();
}

function selectPlan(preferredDay) {
  const plan = plans.find(item => item.id === selector.value);
  day = Object.prototype.hasOwnProperty.call(plan.cards, preferredDay) ? preferredDay : Object.keys(plan.cards)[0];
  renderRoute(plan);
}

async function start() {
  try {
    const response = await fetch("/route-points");
    if (!response.ok) throw new Error("coordinate load failed");
    points = await response.json();
  } catch {
    get("map-source-note").textContent = "暂时无法读取坐标，可以继续看站点和搜索地点。";
  }
  drawLocalPlaces();
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
    const response = await fetch("/route-places");
    if (!response.ok) throw new Error();
    catalog = await response.json();
  } catch { get("edit-feedback").textContent = "地点目录暂未加载，可先移除站点，刷新后再添加。"; }
  selector.disabled = false;
  selector.addEventListener("change", () => selectPlan(""));
  selectPlan(params.get("day") || "");
}

fit.addEventListener("click", () => { stopPlayback(); fitRoute(); });
play.addEventListener("click", playRoute);
start();
