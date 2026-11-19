"use strict";
var _a, _b;
const el = (id) => document.getElementById(id);
const key = "saig-visitor-workspace-v1";
const map = L.map("atlas-map", { minZoom: 9, maxZoom: 16, zoomSnap: 0.25, scrollWheelZoom: true, maxBounds: [[30.37, 114.06], [30.76, 114.56]] });
map.attributionControl.setPrefix(false);
L.imageOverlay("/web/atlas/wuhan-base.webp", [[30.43, 114.12], [30.69, 114.49]], {
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · <a href="https://openmaptiles.org/">OpenMapTiles</a> · <a href="https://openfreemap.org/">OpenFreeMap</a>'
}).addTo(map);
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
  return rows.filter((r) => category === "全部" || r.category === category);
}
function coords(r) {
  return [r.point.lat, r.point.lon];
}
function fit() {
  const current = visible();
  if (!current.length) return;
  map.fitBounds(L.latLngBounds(current.map(coords)), { paddingTopLeft: [54, 54], paddingBottomRight: [54, 60], maxZoom: 14, animate: false });
}
function expand(active) {
  el("atlas-map").parentElement.classList.toggle("expanded", active);
  el("expand").setAttribute("aria-pressed", String(active));
  el("expand").textContent = active ? "收起大图" : "展开大图";
  map.invalidateSize();
  fit();
}
function renderPins() {
  pins.clearLayers();
  const used = [], offsets = [[0, 0], [0, -58], [0, 58], [68, 0], [-68, 0], [66, -51], [-66, 51], [-66, -51], [66, 51]];
  for (const row of visible()) {
    const pos = coords(row), base = map.latLngToLayerPoint(pos);
    const offset = offsets.find(([x, y]) => !used.some((p) => Math.abs(p.x - base.x - x) < 75 && Math.abs(p.y - base.y - y) < 52)) || offsets[0];
    const center = base.add(offset);
    used.push(center);
    const pinPos = map.layerPointToLatLng(center);
    if (offset[0] || offset[1]) {
      L.polyline([pos, pinPos], { weight: 1.5, opacity: 0.8, color: "#557769", interactive: false }).addTo(pins);
      L.circleMarker(pos, { radius: 2.5, color: "#426555", interactive: false }).addTo(pins);
    }
    const picture = node("img");
    picture.src = "/web/atlas/" + row.id + "-pin.webp";
    picture.alt = "";
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
  selected = row;
  el("lookup").value = row.id;
  const img = node("img", null, "portrait");
  img.src = "/web/atlas/" + row.id + ".webp";
  img.alt = row.photo.caption;
  const copy = node("div", null, "detail-copy"), credits = node("details");
  credits.append(
    node("summary", "资料与照片来源"),
    link(row.source_label, row.source),
    document.createElement("br"),
    link(row.photo.caption + " · " + row.photo.artist, row.photo.source),
    document.createTextNode(" · "),
    row.photo.license_url ? link(row.photo.license, row.photo.license_url) : document.createTextNode(row.photo.license)
  );
  const toggle = node("button");
  toggle.id = "toggle-pick";
  toggle.onclick = () => toggleChoice(row.name);
  copy.append(node("small", row.category + " / " + row.area), node("h2", row.name), node("p", row.highlights + "　·　建议 " + row.minutes + " 分钟", "tags"), node("p", row.description));
  if (row.category === "大学") copy.append(node("small", "校园访客预约与开放安排请查学校当期公告。"));
  copy.append(credits, toggle);
  el("detail").replaceChildren(img, copy);
  renderChoice();
  renderPins();
}
function fillPlaces() {
  el("lookup").replaceChildren(...visible().map((r) => new Option(r.name + " · " + r.area, r.id)));
  select(visible()[0]);
  fit();
}
function target() {
  return workspace.plans.find((p) => p.id === el("destination").value);
}
function card() {
  var _a2;
  return (_a2 = target()) == null ? void 0 : _a2.cards[el("atlas-day").value];
}
function fillDays(day) {
  const plan = target(), days = plan ? Object.keys(plan.cards) : ["1"];
  el("atlas-day").replaceChildren(...days.map((d) => new Option("第 " + d + " 天" + ((plan == null ? void 0 : plan.cards[d].calendar_label) ? " · " + plan.cards[d].calendar_label : ""), d)));
  if (days.includes(day)) el("atlas-day").value = day;
  el("day-label").hidden = !plan;
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
    toggle.disabled = busy || already;
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
    el("feedback").textContent = "已更新第 " + day + " 天：" + result.cards[day].order.join(" → ");
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
  map.panTo(coords(r));
};
el("overview").onclick = fit;
el("expand").onclick = () => expand(el("expand").getAttribute("aria-pressed") !== "true");
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && el("expand").getAttribute("aria-pressed") === "true") expand(false);
});
el("destination").onchange = () => {
  clearReceipt();
  fillDays();
};
el("atlas-day").onchange = () => {
  clearReceipt();
  renderChoice();
};
map.setView([30.556, 114.326], 12);
map.on("zoomend", renderPins);
window.addEventListener("pageshow", (e) => {
  if (e.persisted) location.reload();
});
let previousWidth = window.innerWidth;
window.addEventListener("resize", () => {
  map.invalidateSize();
  if (window.innerWidth !== previousWidth) {
    previousWidth = window.innerWidth;
    fit();
  }
});
fillPlans((_a = workspace.mapSelection) == null ? void 0 : _a.plan, (_b = workspace.mapSelection) == null ? void 0 : _b.day);
fetch("/city-places").then((r) => {
  if (!r.ok) throw new Error();
  return r.json();
}).then((data) => {
  rows = data;
  fillPlaces();
}).catch(() => {
  el("feedback").textContent = "地点资料暂未加载，请刷新页面。";
});
