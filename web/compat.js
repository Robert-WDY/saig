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
