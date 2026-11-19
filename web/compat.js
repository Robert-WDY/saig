"use strict";
// A random session ID is a bearer credential, including on a trusted LAN.
function newId() {
  var bytes = new Uint8Array(16);
  (window.crypto || window.msCrypto).getRandomValues(bytes);
  return Array.from(bytes, function (n) { return ("0" + n.toString(16)).slice(-2); }).join("");
}
function lastWhere(rows, predicate) {
  for (var i = rows.length - 1; i >= 0; i--) if (predicate(rows[i])) return rows[i];
}
if (!Element.prototype.replaceChildren) {
  Element.prototype.replaceChildren = function () {
    this.textContent = "";
    this.append.apply(this, arguments);
  };
}
var inviteCode = new URLSearchParams(location.hash.slice(1)).get("invite");
try {
  if (inviteCode) sessionStorage.setItem("saig-invite", inviteCode);
  else inviteCode = sessionStorage.getItem("saig-invite");
} catch (_) {}
if (location.hash.indexOf("#invite=") === 0) history.replaceState(null, "", location.pathname + location.search);
function apiHeaders() {
  var headers = {"Content-Type":"application/json"};
  if (inviteCode) headers["X-SAIG-Invite"] = inviteCode;
  return headers;
}

function setConnection(status) {
  const el = document.getElementById("connection");
  const labels = {online: "接待员在线", offline: "暂时离线"};
  el.className = "connection " + status;
  el.replaceChildren(document.createElement("i"), document.createTextNode(labels[status]));
}

async function checkConnection() {
  try {
    const result = await Promise.race([fetch("/health", {cache: "no-store"}),
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 8000))]);
    setConnection(result.ok ? "online" : "offline");
  } catch {
    setConnection("offline");
  }
}

function markNavigation() {
  var target = ["/city","/routes"].includes(location.pathname) ? location.pathname : location.hash === "#workspace" ? "/#workspace" : "/#assistant";
  document.querySelectorAll(".nav-item").forEach(function (link) {
    var active = link.pathname + link.hash === target;
    link.classList.toggle("current", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
}
markNavigation();
window.addEventListener("hashchange", markNavigation);
checkConnection();

function saveMapResult(workspace, updated, day) {
  var id = updated.plan_id;
  var previous = workspace.plans.find(function (p) { return p.id === id; });
  var replacement = {id:id, title:previous ? previous.title : updated.title, cards:updated.cards,
    version:updated.version, replannedDays:previous ? [Number(day)] : [], beforeCounts:{}};
  if (previous) replacement.beforeCounts[day] = previous.cards[day].order.length;
  workspace.plans = workspace.plans.filter(function (p) {return id !== "current" || p.id !== "preview";});
  var index = workspace.plans.findIndex(function (p) {return p.id === id;});
  if (index < 0) workspace.plans.push(replacement); else workspace.plans[index] = replacement;
  var comparison = workspace.comparison;
  if (comparison && comparison.versions && comparison.versions.some(function (v) {return v.option_id === id;})) comparison.outdated = true;
  workspace.mapSelection = {plan:id, day:day};
  workspace.messages.push({role:"user",text:updated.action},{role:"assistant",result:{answer:updated.answer}});
  sessionStorage.setItem("saig-visitor-workspace-v1", JSON.stringify(workspace));
  return replacement;
}
