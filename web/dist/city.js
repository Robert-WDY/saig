"use strict";
var _a, _b;
const el = (id) => document.getElementById(id);
const key = "saig-visitor-workspace-v1";
const map = WuhanMap.create("atlas-map");
const itinerary = L.layerGroup().addTo(map);
let routePoints = {}, routeMarkers = [], routeFramed = false;
const labels = L.layerGroup().addTo(map);
for (const [name, pos, river] of [["汉口", [30.596, 114.256]], ["武昌", [30.533, 114.32]], ["汉阳", [30.554, 114.225]], ["东湖", [30.568, 114.395], 1], ["长江", [30.567, 114.291], 1], ["汉江", [30.577, 114.239], 1]]) {
  L.marker(pos, { keyboard: false, interactive: false, zIndexOffset: -1e3, icon: L.divIcon({ className: "geo-label" + (river ? " river" : ""), html: name, iconSize: [52, 20] }) }).addTo(labels);
}
const pins = L.layerGroup().addTo(map);
let rows = [], category = "全部", selected = null, choices = /* @__PURE__ */ new Set(), busy = false, attempt = null;
let workspace;
try {
  workspace = JSON.parse(sessionStorage.getItem(key));
} catch {
}
if (!(workspace == null ? void 0 : workspace.session)) workspace = { session: newId(), messages: [], plans: [], comparison: null, pending: null };
function node(tag, text, cls) {
  const out = document.createElement(tag);
  if (text) out.textContent = text;
  if (cls) out.className = cls;
  return out;
}
function link(title, href) {
  const a = node("a", title);
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}
const kinds = { "大学": "university", "景点": "sight", "美食": "food" };
function visible() {
  const query = el("poi-search").value.trim().toLowerCase(), district = el("district").value, topic = el("topic").value;
  return rows.filter((r) => (category === "全部" || r.category === category) && (!district || r.district === district) && (!topic || r.topic === topic) && (!el("only-plan").checked || r.plannable) && (!query || [r.name, r.official_name, r.address, r.district, r.area, r.highlights, r.topic].join(" ").toLowerCase().includes(query)));
}
function coords(r) {
  return [r.point.lat, r.point.lon];
}
function fit() {
  routeFramed = false;
  el("atlas-map").classList.remove("itinerary-focus");
  const current = visible().filter((r) => r.point);
  if (!current.length) return;
  if (current.length === rows.filter((r) => r.point).length) {
    map.fitBounds(WuhanMap.core, { padding: [8, 8], animate: false });
    return;
  }
  map.fitBounds(L.latLngBounds(current.map(coords)), { paddingTopLeft: [54, 54], paddingBottomRight: [54, 60], maxZoom: 14, animate: false });
}
function expand(active) {
  el("atlas-map").parentElement.classList.toggle("expanded", active);
  el("expand").setAttribute("aria-pressed", String(active));
  el("expand").textContent = active ? "收起大图" : "展开大图";
  map.invalidateSize();
  if (routeFramed) fitItinerary();
  else fit();
}
function renderPins() {
  pins.clearLayers();
  const used = routeMarkers.filter(Boolean).map((m) => map.latLngToLayerPoint(m.getLatLng())), offsets = [[0, 0], [0, -58], [0, 58], [68, 0], [-68, 0], [66, -51], [-66, 51], [-66, -51], [66, 51]];
  const matches = visible().filter((r) => r.point), buckets = /* @__PURE__ */ new Map(), singles = [];
  for (const row of matches) {
    if (row === selected || matches.length < 15 || map.getZoom() >= 14) {
      singles.push(row);
      continue;
    }
    const pixel = map.project(coords(row)), key2 = matches.length > 36 && map.getZoom() < 10.5 ? row.district : Math.floor(pixel.x / 64) + "/" + Math.floor(pixel.y / 48);
    if (!buckets.has(key2)) buckets.set(key2, []);
    buckets.get(key2).push(row);
  }
  for (const group of buckets.values()) {
    if (group.length === 1) {
      singles.push(group[0]);
      continue;
    }
    const bounds = L.latLngBounds(group.map(coords));
    const district = group[0].district;
    const regional = map.getZoom() < 10.5 && matches.length > 36 && ["江夏区", "新洲区", "黄陂区", "蔡甸区", "东西湖区"].includes(district);
    const caption = regional ? district.slice(0, -1) + " " + group.length : String(group.length);
    const icon = L.divIcon({
      className: "poi-cluster" + (regional ? " district-count" : ""),
      html: caption,
      iconSize: regional ? [74, 28] : [35, 35],
      iconAnchor: regional ? [37, 14] : [17, 17]
    });
    L.marker(bounds.getCenter(), { icon, title: "展开 " + group.length + " 个地点" }).addTo(pins).on("click", () => {
      const zoom = Math.min(16, Math.max(map.getZoom() + 1, map.getBoundsZoom(bounds, false, [100, 100])));
      map.setView(bounds.getCenter(), zoom, { animate: false });
    });
  }
  for (const row of singles) {
    const pos = coords(row), base = map.latLngToLayerPoint(pos);
    const offset = offsets.find(([x, y]) => !used.some((p) => Math.abs(p.x - base.x - x) < 75 && Math.abs(p.y - base.y - y) < 52)) || offsets[0];
    const center = base.add(offset);
    used.push(center);
    const pinPos = map.layerPointToLatLng(center);
    if (offset[0] || offset[1]) {
      L.polyline([pos, pinPos], { weight: 1.5, opacity: 0.8, color: "#4b5675", interactive: false }).addTo(pins);
      L.circleMarker(pos, { radius: 2.5, color: "#12399d", interactive: false }).addTo(pins);
    }
    const picture = row.photo ? node("img") : node("span", { "公园山水": "山", "展馆文博": "馆", "亲子游乐": "游", "地方美食": "食" }[row.topic] || "景", "pin-symbol");
    if (row.photo) {
      picture.src = "/web/atlas/" + row.id + "-pin.webp";
      picture.alt = "";
    }
    const box = node("div");
    box.append(picture, node("b", row.name));
    const icon = L.divIcon({ className: "atlas-pin " + kinds[row.category] + (selected === row ? " selected" : "") + (choices.has(row.name) ? " chosen" : ""), html: box.innerHTML, iconSize: [78, 56], iconAnchor: [39, 27] });
    const marker = L.marker(pinPos, { icon, title: row.name, alt: row.name, zIndexOffset: selected === row ? 600 : 0 }).addTo(pins);
    if (marker.getElement()) marker.getElement().setAttribute("aria-label", row.name);
    marker.on("click", () => {
      if (el("expand").getAttribute("aria-pressed") === "true") expand(false);
      select(row);
      if (matchMedia("(max-width:800px)").matches) el("detail").scrollIntoView({ block: "start" });
    });
  }
}
function select(row) {
  var _a2;
  selected = row;
  el("lookup").value = row.id;
  const img = row.photo ? node("img", null, "portrait") : null;
  if (img) {
    img.src = "/web/atlas/" + row.id + ".webp";
    img.alt = row.photo.caption;
  }
  const copy = node("div", null, "detail-copy"), credits = node("details");
  credits.append(node("summary", row.photo ? "资料与照片来源" : "地点资料来源"), link(row.source_label, row.source));
  if (row.official_source && row.source !== row.official_source) credits.append(document.createElement("br"), link("武汉市文旅局景区名录", row.official_source));
  if ((_a2 = row.point) == null ? void 0 : _a2.source) credits.append(document.createElement("br"), link(row.point.label || "地图参考位置", row.point.source));
  if (row.photo) credits.append(
    document.createElement("br"),
    link(row.photo.caption + " · " + row.photo.artist, row.photo.source),
    document.createTextNode(" · "),
    row.photo.license_url ? link(row.photo.license, row.photo.license_url) : document.createTextNode(row.photo.license)
  );
  const toggle = node("button");
  toggle.id = "toggle-pick";
  toggle.onclick = () => toggleChoice(row.name);
  copy.append(node("small", row.category + " / " + row.district + (row.grade ? " · " + row.grade : "")), node("h2", row.name), node("p", row.highlights + "　·　建议 " + row.minutes + " 分钟", "tags"), node("p", row.description));
  if (row.category === "大学") copy.append(node("small", "校园访客预约与开放安排请查学校当期公告。"));
  if (row.notice) copy.append(node("p", row.notice, "poi-notice"));
  copy.append(credits, toggle);
  el("detail").replaceChildren(...img ? [img, copy] : [copy]);
  renderChoice();
  renderPins();
}
function fillPlaces() {
  const matches = visible();
  el("matches").textContent = matches.length + " / " + rows.length + " 处";
  el("reset-filters").hidden = matches.length === rows.length && category === "全部" && !el("poi-search").value;
  el("lookup").replaceChildren(...matches.map((r) => new Option(r.name + " · " + r.district, r.id)));
  el("lookup").disabled = !matches.length;
  if (matches.length) {
    select(matches.includes(selected) ? selected : matches[0]);
    fit();
  } else {
    selected = null;
    el("detail").replaceChildren(node("p", "没有符合条件的地点，可以清除筛选或换个关键词。", "detail-copy"));
    renderPins();
  }
}
function target() {
  return workspace.plans.find((p) => p.id === el("destination").value);
}
function card() {
  var _a2;
  return (_a2 = target()) == null ? void 0 : _a2.cards[el("atlas-day").value];
}
function fitItinerary() {
  routeFramed = true;
  el("atlas-map").classList.add("itinerary-focus");
  const locations = routeMarkers.filter(Boolean).map((m) => m.getLatLng());
  if (locations.length) map.fitBounds(locations, { paddingTopLeft: [55, 70], paddingBottomRight: [55, 48], maxZoom: 14, animate: false });
}
function drawItinerary(frame = false) {
  itinerary.clearLayers();
  routeMarkers = [];
  const current = card(), info = el("atlas-itinerary"), list = el("atlas-stops");
  list.replaceChildren();
  info.hidden = !current;
  el("fit-itinerary").hidden = !current;
  if (!current) return;
  el("itinerary-label").textContent = target().title + " · 第 " + el("atlas-day").value + " 天";
  let last = null;
  for (const [i, stop] of WuhanMap.stops(current, routePoints).entries()) {
    const li = node("li"), b = node("button"), number = node("b", String(i + 1));
    b.append(number, node("span", stop.name), node("small", stop.time));
    li.append(b);
    list.append(li);
    if (last && stop.coords) {
      L.polyline([last, stop.coords], { interactive: false, color: "#fff8dd", weight: 8, opacity: 0.96 }).addTo(itinerary);
      L.polyline([last, stop.coords], { interactive: false, color: "#b64a24", weight: 4, dashArray: "9 5", opacity: 1 }).addTo(itinerary);
    }
    last = stop.coords;
    if (!stop.coords) {
      b.disabled = true;
      b.append(node("small", "位置待核实"));
      routeMarkers.push(null);
      continue;
    }
    const icon = L.divIcon({ className: "atlas-step", html: String(i + 1), iconSize: [30, 30], iconAnchor: [15, 15] });
    const marker = L.marker(stop.coords, { icon, title: i + 1 + " · " + stop.name, zIndexOffset: 1800 }).addTo(itinerary);
    const popup = node("div");
    popup.append(node("strong", stop.name), node("p", stop.time));
    marker.bindPopup(popup);
    routeMarkers.push(marker);
    b.onclick = () => {
      map.setView(stop.coords, Math.max(map.getZoom(), 13), { animate: false });
      marker.openPopup();
    };
  }
  el("fit-itinerary").disabled = !routeMarkers.some(Boolean);
  el("route-editor-link").href = "/routes?" + new URLSearchParams({ plan: target().id, day: el("atlas-day").value });
  renderPins();
  if (frame) fitItinerary();
}
function fillDays(day) {
  const plan = target(), days = plan ? Object.keys(plan.cards) : ["1"];
  el("atlas-day").replaceChildren(...days.map((d) => new Option("第 " + d + " 天" + ((plan == null ? void 0 : plan.cards[d].calendar_label) ? " · " + plan.cards[d].calendar_label : ""), d)));
  if (days.includes(day)) el("atlas-day").value = day;
  el("day-label").hidden = !plan;
  drawItinerary(true);
  renderChoice();
}
function fillPlans(plan, day) {
  el("destination").replaceChildren(...workspace.plans.map((p) => new Option(p.title, p.id)), new Option("新建一日游 · 09:00–18:00", "new"));
  if (plan && workspace.plans.some((p) => p.id === plan)) el("destination").value = plan;
  fillDays(day);
}
function clearReceipt() {
  attempt = null;
  el("feedback").textContent = "";
  el("open-route").hidden = true;
}
function toggleChoice(name) {
  if (busy) return;
  if (choices.has(name)) choices.delete(name);
  else choices.add(name);
  clearReceipt();
  renderChoice();
  renderPins();
}
function renderChoice() {
  var _a2;
  const existing = ((_a2 = card()) == null ? void 0 : _a2.order) || [], add = [...choices].filter((n) => !existing.includes(n));
  const toggle = el("toggle-pick");
  if (toggle && selected) {
    const already = existing.includes(selected.name), picked = choices.has(selected.name);
    toggle.textContent = already ? "已在当天行程" : picked ? "已选中 · 移出选点" : "＋ 选入行程";
    if (!selected.plannable) toggle.textContent = "仅供浏览 · 暂不编排行程";
    toggle.disabled = busy || already || !selected.plannable;
    toggle.setAttribute("aria-pressed", String(picked || already));
  }
  el("picked").replaceChildren(...[...choices].map((n) => {
    const b = node("button", n + (existing.includes(n) ? "（已在行程）" : "") + " ×");
    b.disabled = busy;
    b.onclick = () => toggleChoice(n);
    return b;
  }));
  el("count").textContent = String(choices.size);
  el("apply").disabled = busy || !add.length;
  el("apply").textContent = busy ? "正在规划…" : target() ? "加入当天并重新规划" : "生成一日游";
  el("destination").disabled = busy;
  el("atlas-day").disabled = busy;
}
el("apply").onclick = async () => {
  if (busy) return;
  const plan = target(), day = el("atlas-day").value, old = card();
  const add = [...choices].filter((n) => !(old == null ? void 0 : old.order.includes(n)));
  if (!add.length) return;
  busy = true;
  renderChoice();
  attempt = attempt || newId();
  try {
    sessionStorage.setItem(key, JSON.stringify(workspace));
    const change = { plan: (plan == null ? void 0 : plan.id) || "new", day, add, remove: [] };
    if (old) change.basis = { order: old.order, contract: old.contract };
    const res = await fetch("/route-edit", { method: "POST", headers: apiHeaders(), body: JSON.stringify({ session: workspace.session, request_id: attempt, change }) });
    const result = await res.json();
    if (!res.ok) throw new Error(result.error || "规划失败，请重新选择。");
    saveMapResult(workspace, result, day);
    choices.clear();
    attempt = null;
    fillPlans(result.plan_id, day);
    renderPins();
    el("feedback").textContent = "已更新第 " + day + " 天：" + result.cards[day].order.join(" → ") + "。" + routeTime.change(old, result.cards[day]) + "。";
    const route = el("open-route");
    route.href = "/routes?plan=" + encodeURIComponent(result.plan_id) + "&day=" + day;
    route.hidden = false;
  } catch (err) {
    el("feedback").textContent = err.message || "暂未收到结果，可再次提交。";
  } finally {
    busy = false;
    renderChoice();
  }
};
el("filters").onclick = (e) => {
  if (e.target.tagName !== "BUTTON" || !rows.length) return;
  category = e.target.textContent;
  el("filters").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.target)));
  fillPlaces();
};
el("lookup").onchange = () => {
  const r = rows.find((r2) => r2.id === el("lookup").value);
  select(r);
  if (r.point) map.setView(coords(r), Math.max(13, map.getZoom()));
};
el("poi-search").oninput = fillPlaces;
for (const id of ["district", "topic", "only-plan"]) el(id).onchange = fillPlaces;
el("reset-filters").onclick = () => {
  for (const id of ["district", "topic", "poi-search"]) el(id).value = "";
  el("only-plan").checked = false;
  el("filters").querySelector("button").click();
};
el("fit-itinerary").onclick = fitItinerary;
el("overview").onclick = () => {
  routeFramed = false;
  el("atlas-map").classList.remove("itinerary-focus");
  map.fitBounds(WuhanMap.bounds, { padding: [12, 12], animate: false });
};
el("core-view").onclick = () => {
  routeFramed = false;
  el("atlas-map").classList.remove("itinerary-focus");
  map.fitBounds(WuhanMap.core, { padding: [8, 8], animate: false });
};
el("expand").onclick = () => expand(el("expand").getAttribute("aria-pressed") !== "true");
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && el("expand").getAttribute("aria-pressed") === "true") expand(false);
});
function rememberSelection() {
  if (!target()) return;
  workspace.mapSelection = { plan: target().id, day: el("atlas-day").value };
  try {
    sessionStorage.setItem(key, JSON.stringify(workspace));
  } catch {
  }
  history.replaceState(null, "", "/city?" + new URLSearchParams(workspace.mapSelection));
}
el("destination").onchange = () => {
  clearReceipt();
  fillDays();
  rememberSelection();
};
el("atlas-day").onchange = () => {
  clearReceipt();
  renderChoice();
  drawItinerary(true);
  rememberSelection();
};
map.on("zoomend", renderPins);
window.addEventListener("pageshow", (e) => {
  if (e.persisted) location.reload();
});
let previousWidth = window.innerWidth;
window.addEventListener("resize", () => {
  map.invalidateSize();
  if (window.innerWidth !== previousWidth) {
    previousWidth = window.innerWidth;
    if (routeFramed) fitItinerary();
    else fit();
  }
});
const requested = new URLSearchParams(location.search);
const requestedPlan = workspace.plans.find((p) => p.id === requested.get("plan"));
fillPlans((requestedPlan == null ? void 0 : requestedPlan.id) || ((_a = workspace.mapSelection) == null ? void 0 : _a.plan), requestedPlan ? requested.get("day") : (_b = workspace.mapSelection) == null ? void 0 : _b.day);
Promise.all([WuhanMap.readJSON("/city-places"), WuhanMap.readJSON("/route-points").catch(() => ({}))]).then(([data, points]) => {
  rows = data;
  routePoints = { ...points };
  for (const row of rows) if (row.point) routePoints[row.name] = row.point;
  for (const id of ["district", "topic"]) for (const value of [...new Set(rows.map((r) => r[id]))].sort((a, b) => a.localeCompare(b, "zh-CN"))) el(id).append(new Option(value, value));
  fillPlaces();
  drawItinerary(true);
}).catch(() => {
  el("feedback").textContent = "地点资料暂未加载，请刷新页面。";
});
