"use strict";
var _a, _b, _c, _d, _e, _f, _g, _h, _i;
const get = (id) => document.getElementById(id);
const question = get("question");
const chatWindow = get("chat-window");
const messages = get("messages");
const planPrompt = document.querySelector(".starter[data-prompt*='一日游']").dataset.prompt;
const storageKey = "saig-visitor-workspace-v1";
const modes = { walk: "步行", metro: "地铁", transit: "公共交通", taxi: "打车", estimate: "转场" };
const defaultState = () => ({ session: newId(), messages: [], plans: [], comparison: null, pending: null });
let state = restore();
let busy = false;
let activeTab = "plans";
let selectedPlan = ((_a = state.mapSelection) == null ? void 0 : _a.plan) || ((_b = state.plans[0]) == null ? void 0 : _b.id) || "";
let openDay = ((_c = state.mapSelection) == null ? void 0 : _c.day) || "1";
let animateReply = false;
let routePoints = null;
let streamedReply = false;
function restore() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey));
    if ((saved == null ? void 0 : saved.session) && Array.isArray(saved.messages) && Array.isArray(saved.plans)) return saved;
  } catch {
  }
  return defaultState();
}
function save() {
  try {
    state.mapSelection = { plan: selectedPlan, day: openDay };
    sessionStorage.setItem(storageKey, JSON.stringify(state));
  } catch {
  }
}
function node(tag, className = "", content = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== "") element.textContent = content;
  return element;
}
function button(className, label, onClick) {
  const el = node("button", className, label);
  el.type = "button";
  el.addEventListener("click", onClick);
  return el;
}
function link(label, href, className = "") {
  try {
    const url = new URL(href);
    if (!["https:", "http:"].includes(url.protocol)) return null;
    const a = node("a", className, label);
    a.href = url.href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  } catch {
    return null;
  }
}
function paragraphs(parent, text = "", notes = null) {
  for (const line of text.trim().split(/\r?\n/)) {
    if (!line.trim()) continue;
    const p = node("p", /^\s*第\d+天/.test(line) ? "route-snippet" : "");
    const tokens = line.replace(/^\s*#{1,6}\s+/, "").split(/(https?:\/\/[^\s，。；、）]+|\*\*[^*]+\*\*)/g);
    for (const token of tokens) {
      if (token.startsWith("**") && token.endsWith("**")) p.append(node("strong", "", token.slice(2, -2)));
      else if (/^https?:\/\//.test(token)) p.append(link(token, token) || document.createTextNode(token));
      else p.append(document.createTextNode(token));
    }
    for (const number of (notes == null ? void 0 : notes.get(line.trim())) || []) {
      const mark = button("footnote", "[" + number + "]", () => focusSource(parent.closest(".bubble"), number));
      mark.setAttribute("aria-label", "查看第 " + number + " 条出处");
      p.append(mark);
    }
    parent.append(p);
  }
}
function currentReply() {
  var _a2;
  return (_a2 = lastWhere(state.messages, (message) => message.role === "assistant")) == null ? void 0 : _a2.result;
}
function showTab(tab, focus = false) {
  setTimeout(drawBoardMap, 0);
  activeTab = tab;
  for (const [name, id] of [["plans", "plans-tab"], ["comparison", "comparison-tab"]]) {
    const selected = name === tab;
    const el = get(id);
    el.setAttribute("aria-selected", selected);
    el.tabIndex = selected ? 0 : -1;
    get(name).hidden = !selected;
  }
  get("save-comparison").hidden = tab !== "comparison" || !currentComparison();
  if (focus) get(tab === "plans" ? "plans-tab" : "comparison-tab").focus();
}
function revealBoard(tab, id, days) {
  if (id && state.plans.some((plan) => plan.id === id)) {
    selectedPlan = id;
    openDay = String((days == null ? void 0 : days[0]) || 1);
    renderBoard();
  }
  showTab(tab);
  get("workspace").scrollIntoView({ block: "nearest" });
  get(tab === "plans" ? "plans-tab" : "comparison-tab").focus({ preventScroll: true });
}
function viewDeliverable(delivery) {
  var _a2;
  if (delivery.kind === "compare") revealBoard("comparison");
  else {
    const id = delivery.kind === "adopt" ? "current" : delivery.option_id || ((_a2 = delivery.inputs) == null ? void 0 : _a2[0]);
    revealBoard("plans", id, delivery.replanned_days);
  }
}
function sourceLabel(citation) {
  const title = citation.title || "来源";
  return /^\d+$/.test(String(citation.locator || "")) ? title + " · 第 " + citation.locator + " 页" : title + (citation.locator ? " · " + citation.locator : "");
}
function citationIndex(citations = []) {
  const order = [], notes = /* @__PURE__ */ new Map();
  for (const citation of citations) {
    const key = sourceLabel(citation) + "|" + citation.source;
    let number = order.findIndex((item) => item.key === key) + 1;
    if (!number) {
      order.push({ key, citation, quotes: [] });
      number = order.length;
    }
    if (citation.quote && !order[number - 1].quotes.includes(citation.quote)) order[number - 1].quotes.push(citation.quote);
    const claim = (citation.claim || "").trim();
    if (claim) notes.set(claim, [.../* @__PURE__ */ new Set([...notes.get(claim) || [], number])]);
  }
  return { order, notes };
}
function appendSources(parent, index) {
  if (!index.order.length) return;
  const details = node("details", "sources");
  const list = node("ol", "source-list");
  for (const [i, item] of index.order.entries()) {
    const row = node("li", "source-item");
    row.dataset.source = String(i + 1);
    row.append(node("b", "", "[" + (i + 1) + "]"));
    const a = link(sourceLabel(item.citation) + " ↗", item.citation.source, "source");
    row.append(a || node("span", "", sourceLabel(item.citation)));
    if (item.quotes[0]) row.append(node("q", "", item.quotes[0].length > 90 ? item.quotes[0].slice(0, 90) + "…" : item.quotes[0]));
    list.append(row);
  }
  details.append(node("summary", "", "资料出处 · " + index.order.length + " 条官方来源"), list);
  parent.append(details);
}
function focusSource(bubble, number) {
  const details = bubble == null ? void 0 : bubble.querySelector(".sources");
  if (!details) return;
  details.open = true;
  const row = details.querySelector('[data-source="' + number + '"]');
  if (!row) return;
  row.classList.remove("flash");
  void row.offsetWidth;
  row.classList.add("flash");
  row.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
const topicLabels = {
  wuhan: "介绍武汉",
  attraction: "武汉景点",
  food: "武汉美食",
  community: "数命 SPU 社区",
  spu: "数命 SPU",
  saig: "SAIG 大赛",
  guide: "旅游规划",
  location: "位置"
};
function replyTopics(result) {
  if (Array.isArray(result.topics)) return result.topics.slice(0, 3);
  const found = [];
  const planned = ["plan", "edit", "preview"].includes(result.mode) && (Object.keys(result.days || {}).length || Object.keys(result.preview || {}).length);
  if (planned || (result.deliverables || []).some((d) => d.cards)) found.push("旅游规划");
  for (const step of result.trace || []) {
    const name = step.tool_name || (step.query !== void 0 ? step.tool : "");
    if (step.step === "answered_question" && !step.supported) continue;
    const label = topicLabels[name];
    if (label && !found.includes(label)) found.push(label);
  }
  return found.slice(0, 3);
}
function planSummary(result) {
  if (Array.isArray(result.summary_lines)) return result.summary_lines;
  return (result.answer || "").split("\n").filter((line) => /^第\d+天[：:]/.test(line)).map((line) => line.replace(/\s*参考《[^》]*》.*$/, "").replace(/\d{1,2}:\d{2}–\d{1,2}:\d{2}\s*/g, ""));
}
function spokenReply(result) {
  const days = planSummary(result);
  if (days.length) return "好的，行程排好啦。" + days.join("。") + "。每一站的时间和交通都在行程板上。";
  return (result.answer || "").split("\n").slice(0, 3).join("");
}
let showcase = null, placeIndex = {};
fetch("/city-places").then((r) => r.ok ? r.json() : []).then((rows) => {
  for (const row of rows) placeIndex[row.name] = row;
  if (rows.length) renderBoard();
}).catch(() => {
});
if (typeof WuhanMap !== "undefined") WuhanMap.readJSON("/route-points").then((points) => {
  routePoints = points;
  if (state.plans.length) renderBoard();
}).catch(() => {
});
fetch("/showcase").then((r) => r.ok ? r.json() : null).then((data) => {
  showcase = data;
  if (data) renderMessages();
}).catch(() => {
});
function appendInfoCards(bubble, result) {
  if (!showcase) return;
  const topics = result.topics || [];
  if (topics.includes("数命 SPU 社区")) {
    const venue = showcase.venue, card = node("section", "info-card venue-card");
    const pin = node("div", "venue-pin");
    pin.setAttribute("aria-hidden", "true");
    pin.append(node("span", "pin-dot"), node("span", "pin-ring"));
    const copy = node("div", "venue-copy");
    copy.append(node("small", "", "数命 SPU 社区 · 江岸会场"), node("strong", "", venue.place), node("p", "", venue.district));
    const lines = node("div", "metro-list");
    for (const station of venue.metro) {
      const row = node("span", "metro");
      row.append(node("b", "", "M"), node("span", "", station.name + " · " + station.lines));
      lines.append(row);
    }
    copy.append(lines);
    const actions = node("div", "info-actions");
    const open = node("a", "btn secondary sm", "在武汉地图上看");
    open.href = "/city?" + new URLSearchParams({ place: venue.place });
    actions.append(open, node("small", "", venue.note));
    copy.append(actions);
    card.append(pin, copy);
    bubble.append(card);
  }
  if (topics.includes("SAIG 大赛")) {
    const card = node("section", "info-card timeline-card");
    card.append(node("small", "", "SAIG 赛程 · " + showcase.checked));
    const list = node("ol", "timeline");
    for (const item of showcase.timeline) {
      const row = node("li", item.highlight ? "now" : "");
      row.append(node("time", "", item.date), node("span", "", item.text));
      list.append(row);
    }
    card.append(list);
    const source = link("以官网公告为准 ↗", showcase.source, "source-link");
    if (source) card.append(source);
    bubble.append(card);
  }
}
function renderReply(bubble, result) {
  const deliveries = result.deliverables || [];
  const visibleCards = deliveries.filter((d) => d.status === "passed" && (d.cards || d.kind === "compare"));
  const body = node("div", "message-body");
  if (visibleCards.length) {
    const list = node("div", "delivery-list");
    for (const delivery of visibleCards) {
      const prefix = delivery.kind === "compare" ? "比较" : delivery.kind === "revise" ? "行程已更新" : delivery.kind === "adopt" ? "已采用" : "查看行程";
      const label = delivery.cards ? Object.keys(delivery.cards).length + " 天" : "↗";
      const el = button("delivery", "", () => viewDeliverable(delivery));
      el.append(node("span", "", prefix + " · " + delivery.title), node("span", "arrow", label));
      list.append(el);
    }
    for (const item of deliveries.filter((d) => !visibleCards.includes(d))) {
      if (item.status === "passed") paragraphs(list, item.answer);
      else list.append(node("p", "failed", item.title + " · " + item.answer));
    }
    bubble.append(list);
    const details = node("details", "answer-detail");
    details.append(node("summary", "", "展开完整回答"), body);
    bubble.append(details);
  } else if (planSummary(result).length) {
    const summary = node("div", "plan-summary");
    for (const line of planSummary(result)) {
      const [day, stops = ""] = line.split(/[：:](.*)/s);
      const row = node("p", "summary-day");
      row.append(node("b", "", day), node("span", "", stops.trim()));
      summary.append(row);
    }
    summary.append(button("btn secondary sm plan-jump", "查看每站时间和交通", () => {
      get("workspace").scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    bubble.append(summary);
    const details = node("details", "answer-detail");
    details.append(node("summary", "", "展开完整安排与转场"), body);
    bubble.append(details);
  } else {
    bubble.append(body);
  }
  const index = citationIndex(result.citations);
  paragraphs(body, result.answer, index.notes);
  appendInfoCards(bubble, result);
  appendSources(bubble, index);
}
function renderMessages() {
  var _a2;
  get("welcome").hidden = state.messages.length > 0;
  const fragment = document.createDocumentFragment();
  for (const message of state.messages) {
    const entry = node("article", "message " + message.role);
    if (animateReply && message === state.messages[state.messages.length - 1] && message.role === "assistant") entry.classList.add("reply-in");
    const bubble = node("div", "bubble");
    if (message.role === "user") bubble.textContent = message.text;
    else {
      const mark = node("span", "receptionist-face");
      mark.setAttribute("aria-hidden", "true");
      entry.append(mark);
      bubble.setAttribute("aria-label", "接待员的回答");
      if ((_a2 = message.result.topics) == null ? void 0 : _a2.length) {
        const tags = node("div", "topic-tags");
        for (const topic of message.result.topics) tags.append(node("span", "", topic));
        bubble.append(tags);
      }
      renderReply(bubble, message.result);
    }
    entry.append(bubble);
    fragment.append(entry);
  }
  if (state.pending) {
    const entry = node("div", busy ? "message" : "message error");
    const bubble = node("div", "bubble");
    if (busy) {
      const mark = node("span", "receptionist-face");
      mark.setAttribute("aria-hidden", "true");
      entry.prepend(mark);
      bubble.append(node("p", "working", "江豚接待员正在处理…"));
      const steps = node("ol", "work-steps");
      steps.id = "work-steps";
      for (const label of workPlan(state.pending.text)) steps.append(node("li", "", label));
      bubble.append(steps);
    } else {
      bubble.append(node("p", "", state.pending.error || "这条消息还在等答复。"));
      bubble.append(button("chip", "重试发送", () => sendPending()));
    }
    entry.append(bubble);
    fragment.append(entry);
  }
  messages.replaceChildren(fragment);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}
const tripWords = /几天|[一两二三四五1-5]日|天游|行程|路线|排|规划|改|推迟|提前|出发|换成|加上|去掉|删掉/;
function workPlan(text = "") {
  return tripWords.test(text) ? ["理解行程要求", "挑选手册里的攻略", "计算站点间交通", "审核时间与约束"] : ["理解你的问题", "检索官方资料", "核对每条引文", "整理成答复"];
}
function tickSteps(elapsed) {
  var _a2;
  if (((_a2 = get("work-steps")) == null ? void 0 : _a2.dataset.mode) === "live") return;
  const items = document.querySelectorAll("#work-steps li");
  const pace = [0, 1.2, 3.2, 6.5];
  items.forEach((item, i) => {
    const active = elapsed >= pace[i] && (i === items.length - 1 || elapsed < pace[i + 1]);
    item.className = elapsed >= pace[i + 1] && i < items.length - 1 ? "done" : active ? "active" : "";
  });
}
function typeReply() {
  const entry = messages.querySelector(".message.assistant.reply-in:last-child") || [...messages.querySelectorAll(".message.assistant")].pop();
  if (!entry || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const blocks = [...entry.querySelectorAll(".message-body > p, .summary-day span")].filter((el) => !el.closest("details:not([open])"));
  const texts = blocks.map((block2) => {
    const nodes = [...block2.childNodes].filter((n) => n.nodeType === Node.TEXT_NODE);
    return nodes.map((n) => {
      const value = n.textContent;
      n.textContent = "";
      return [n, value];
    });
  });
  const extras = entry.querySelectorAll(".info-card, .sources, .footnote, .plan-summary .delivery, .answer-detail");
  extras.forEach((el) => el.classList.add("pending-reveal"));
  const total = texts.flat().reduce((sum, [, value]) => sum + value.length, 0);
  const perTick = Math.max(2, Math.ceil(total / 110));
  let block = 0, part = 0, offset = 0;
  const timer = setInterval(() => {
    let budget = perTick;
    while (budget > 0 && block < texts.length) {
      const pieces = texts[block];
      if (part >= pieces.length) {
        block++;
        part = 0;
        continue;
      }
      const [n, value] = pieces[part];
      const take = Math.min(budget, value.length - offset);
      n.textContent += value.slice(offset, offset + take);
      offset += take;
      budget -= take;
      if (offset >= value.length) {
        part++;
        offset = 0;
      }
    }
    if (block >= texts.length) {
      clearInterval(timer);
      extras.forEach((el) => el.classList.remove("pending-reveal"));
    }
  }, 28);
}
const Amap = /* @__PURE__ */ (() => {
  const a = 6378245, ee = 0.006693421622965943;
  const tLat = (x, y) => {
    let r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
    r += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    r += (20 * Math.sin(y * Math.PI) + 40 * Math.sin(y / 3 * Math.PI)) * 2 / 3;
    return r + (160 * Math.sin(y / 12 * Math.PI) + 320 * Math.sin(y * Math.PI / 30)) * 2 / 3;
  };
  const tLon = (x, y) => {
    let r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
    r += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    r += (20 * Math.sin(x * Math.PI) + 40 * Math.sin(x / 3 * Math.PI)) * 2 / 3;
    return r + (150 * Math.sin(x / 12 * Math.PI) + 300 * Math.sin(x / 30 * Math.PI)) * 2 / 3;
  };
  function gcj(lat, lon) {
    let dLat = tLat(lon - 105, lat - 35), dLon = tLon(lon - 105, lat - 35);
    const rad = lat / 180 * Math.PI, m = 1 - ee * Math.sin(rad) ** 2, sq = Math.sqrt(m);
    dLat = dLat * 180 / (a * (1 - ee) / (m * sq) * Math.PI);
    dLon = dLon * 180 / (a / sq * Math.cos(rad) * Math.PI);
    return [lon + dLon, lat + dLat].map((v) => v.toFixed(6));
  }
  const point = (name) => {
    const p = routePoints == null ? void 0 : routePoints[name];
    return p && Number.isFinite(p.lat) && Number.isFinite(p.lon) ? gcj(p.lat, p.lon) : null;
  };
  const pin = (name) => {
    const p = point(name);
    return p && p.join(",") + "," + encodeURIComponent(name);
  };
  const MODE = { walk: "walk", metro: "bus", transit: "bus", bus: "bus", taxi: "car", car: "car" };
  return {
    navigate(from, to, mode) {
      const a2 = pin(from), b = pin(to);
      if (!b) return "https://uri.amap.com/search?keyword=" + encodeURIComponent(to) + "&city=武汉&src=wuhan-switchboard&callnative=1";
      return "https://uri.amap.com/navigation?" + (a2 ? "from=" + a2 + "&" : "") + "to=" + b + "&mode=" + (MODE[mode] || "bus") + "&city=武汉&coordinate=gaode&src=wuhan-switchboard&callnative=1";
    },
    day(card) {
      var _a2, _b2, _c2;
      const names = [(_a2 = card.contract) == null ? void 0 : _a2.origin, ...(((_b2 = card.audit) == null ? void 0 : _b2.stops) || []).map((s) => s.place), (_c2 = card.contract) == null ? void 0 : _c2.destination].filter(Boolean);
      const pins = [...new Set(names)].map(pin).filter(Boolean).slice(0, 10);
      return pins.length ? "https://uri.amap.com/marker?markers=" + pins.join("|") + "&src=wuhan-switchboard&callnative=1" : null;
    }
  };
})();
function stopRow(name, time, leg, arrival = false, exact = "", change = null) {
  const row = node("li", (arrival ? "arrival" : "") + (change ? " changed " + change.kind : ""));
  const clock = node("time", "", time);
  if (exact) clock.title = "计划原值 " + exact;
  if (change == null ? void 0 : change.oldTime) {
    const was = node("del", "was", change.oldTime);
    was.setAttribute("aria-label", "原为 " + change.oldTime);
    clock.prepend(was);
  }
  const label = node("span", "", name);
  if (typeof MapIcons !== "undefined" && !arrival) {
    const icon = node("i", "stop-icon");
    const place = name.replace(/出发$/, "");
    icon.innerHTML = MapIcons.for(placeIndex[place] || { name: place }, 16);
    label.prepend(icon);
  }
  if ((change == null ? void 0 : change.kind) === "added") label.append(node("em", "change-tag", "新增"));
  if ((change == null ? void 0 : change.kind) === "moved") label.append(node("em", "change-tag", change.delta));
  row.append(clock, label);
  if (leg) {
    const how = ["metro", "transit", "bus"].includes(leg.mode) ? leg.directions : "";
    const description = [modes[leg.mode], Number.isFinite(leg.minutes) ? routeTime.duration(leg.minutes) : "", how].filter(Boolean).join(" · ");
    const legLine = node("span", "leg", description);
    if (leg.origin && leg.destination && leg.origin !== leg.destination) {
      const nav = link("", Amap.navigate(leg.origin, leg.destination, leg.mode), "amap-nav");
      nav.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0 1 13 0c0 4.8-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.4"/></svg>';
      nav.title = "用高德导航：" + leg.origin + " 到 " + leg.destination;
      nav.setAttribute("aria-label", nav.title);
      legLine.append(" ", nav);
    }
    row.append(legLine);
  }
  return row;
}
function stopChange(stop, before, contract) {
  var _a2;
  if (!before) return null;
  const old = (((_a2 = before.audit) == null ? void 0 : _a2.stops) || []).find((item) => item.place === stop.place);
  if (!old) return { kind: "added" };
  if (old.start === stop.start) return null;
  const minutes = stop.start - old.start;
  return {
    kind: "moved",
    oldTime: routeTime.stop(old, before.contract || contract),
    delta: (minutes > 0 ? "推后 " : "提前 ") + routeTime.duration(Math.abs(minutes))
  };
}
function daySection(number, day, open, before = null) {
  var _a2, _b2, _c2, _d2, _e2, _f2, _g2;
  const details = node("details", before ? "day-card has-changes" : "day-card");
  details.open = open;
  const stops = ((_a2 = day.audit) == null ? void 0 : _a2.stops) || [];
  const summary = node("summary", "", "第 " + number + " 天");
  summary.append(node("small", "", stops.length + " 站"));
  if (before) summary.append(node("span", "changed-badge", "已更新"));
  const list = node("ol", "stops");
  const contract = day.contract || {};
  const legs = ((_b2 = day.audit) == null ? void 0 : _b2.legs) || [];
  if (!stops.length) {
    summary.querySelector("small").textContent = "自由活动";
    list.append(node("li", "free-day", "这一天不排景点，自由活动" + (contract.origin ? "（住" + contract.origin + "）" : "")));
    details.append(summary, list);
    return details;
  }
  if (contract.origin && contract.origin !== ((_c2 = stops[0]) == null ? void 0 : _c2.place)) {
    const was = (_d2 = before == null ? void 0 : before.contract) == null ? void 0 : _d2.start;
    list.append(stopRow(
      contract.origin + "出发",
      routeTime.exact(contract.start),
      null,
      false,
      "",
      Number.isFinite(was) && was !== contract.start ? {
        kind: "moved",
        oldTime: routeTime.exact(was),
        delta: (contract.start > was ? "推后 " : "提前 ") + routeTime.duration(Math.abs(contract.start - was))
      } : null
    ));
  }
  for (const stop of stops) {
    const leg = legs.find((item) => item.destination === stop.place && item.origin !== item.destination);
    list.append(stopRow(
      stop.place,
      routeTime.stop(stop, contract),
      leg,
      false,
      routeTime.exact(stop.start) + "–" + routeTime.exact(stop.end),
      stopChange(stop, before, contract)
    ));
  }
  const removed = (((_e2 = before == null ? void 0 : before.audit) == null ? void 0 : _e2.stops) || []).filter((old) => !stops.some((stop) => stop.place === old.place));
  if (removed.length) list.append(node("li", "removed", "已移除：" + removed.map((stop) => stop.place).join("、")));
  if (contract.destination) {
    const limit = contract.end - (contract.buffer || 0);
    const arrival = routeTime.arrival((_f2 = day.audit) == null ? void 0 : _f2.arrival, limit);
    list.append(stopRow(
      "预计抵达 " + contract.destination + " · 最晚 " + routeTime.exact(limit),
      arrival,
      lastWhere(legs, (item) => item.destination === contract.destination),
      true,
      routeTime.exact((_g2 = day.audit) == null ? void 0 : _g2.arrival)
    ));
  }
  details.append(summary, list);
  if (day.guide_source) {
    const guide = link("参考 · " + day.guide_source.title + " ↗", day.guide_source.source, "guide");
    if (guide) details.append(guide);
  }
  return details;
}
function planCard(plan) {
  var _a2, _b2, _c2, _d2, _e2, _f2, _g2, _h2, _i2;
  const selected = selectedPlan === plan.id;
  const card = node("article", selected ? "plan selected" : "plan");
  const heading = button("plan-header", "", () => {
    var _a3, _b3;
    selectedPlan = selected ? "" : plan.id;
    openDay = String(((_a3 = plan.replannedDays) == null ? void 0 : _a3[0]) || 1);
    const top = get("plans").scrollTop;
    renderBoard();
    get("plans").scrollTop = top;
    (_b3 = document.getElementById(heading.id)) == null ? void 0 : _b3.focus({ preventScroll: true });
  });
  heading.id = "plan-toggle-" + plan.id;
  heading.setAttribute("aria-expanded", selected);
  const meta = Object.keys(plan.cards).length + " 天" + (plan.version > 1 ? " · v" + plan.version : "");
  heading.append(node("span", "plan-title", plan.title), node("span", "plan-meta", meta));
  card.append(heading);
  if (!selected) return card;
  const content = node("div", "plan-content");
  if ((_a2 = plan.replannedDays) == null ? void 0 : _a2.length) {
    const summary = node("div", animateReply ? "plan-note plan-flash" : "plan-note");
    summary.append(node("p", "", "本轮更新第 " + plan.replannedDays.join("、") + " 天"));
    for (const day of plan.replannedDays) {
      const card2 = plan.cards[day];
      const contract = card2 == null ? void 0 : card2.contract;
      const before = (_b2 = plan.beforeCounts) == null ? void 0 : _b2[day];
      const after = (_d2 = (_c2 = card2 == null ? void 0 : card2.audit) == null ? void 0 : _c2.stops) == null ? void 0 : _d2.length;
      if (Number.isInteger(before) && Number.isInteger(after) && before !== after) {
        summary.append(node("p", "stop-change", before + " 站 → " + after + " 站"));
      }
      if (!(contract == null ? void 0 : contract.destination)) continue;
      const limit = contract.end - (contract.buffer || 0);
      if ((_f2 = (_e2 = card2.audit) == null ? void 0 : _e2.stops) == null ? void 0 : _f2.length) summary.append(node("p", "", "预计 " + routeTime.arrival((_g2 = card2.audit) == null ? void 0 : _g2.arrival, limit) + " 到" + contract.destination + " · 最晚 " + routeTime.exact(limit)));
    }
    content.append(summary);
  }
  for (const [day, details] of Object.entries(plan.cards)) {
    const before = ((_h2 = plan.changedDays) == null ? void 0 : _h2.includes(day)) ? (_i2 = plan.previous) == null ? void 0 : _i2[day] : null;
    const section = daySection(day, details, day === openDay, before);
    section.addEventListener("toggle", () => {
      if (section.isConnected && section.open) {
        openDay = day;
        updateMapLink();
        drawBoardMap();
      }
    });
    content.append(section);
  }
  card.append(content);
  return card;
}
function emptyBoard(title, copy, action) {
  const el = node("div", "empty-board");
  const symbol = node("div", "route-symbol");
  symbol.setAttribute("aria-hidden", "true");
  symbol.append(node("span"), node("span"), node("span"));
  el.append(symbol, node("h3", "", title), node("p", "", copy));
  if (action) el.append(button("btn primary", action.label.replace(/\s*[↗→]$/, ""), action.click));
  return el;
}
function compareAgain() {
  const candidates = state.plans.filter((plan) => plan.id !== "current" && plan.id !== "preview");
  if (candidates.length === 2) fill("请比较「" + candidates[0].title + "」和「" + candidates[1].title + "」的最新方案。");
  else fill("请比较这两份行程：");
}
function comparisonView(result) {
  var _a2;
  const container = node("div", "comparison-body");
  for (const version of result.versions || []) {
    const plan = state.plans.find((p) => p.id === version.option_id);
    const stats = (_a2 = result.metrics) == null ? void 0 : _a2[version.input];
    if (!stats) continue;
    const card = node("section", "comparison-card");
    const title = (plan == null ? void 0 : plan.title) || "行程方案";
    card.append(node("h3", "", title + (version.version > 1 ? " · v" + version.version : "")));
    card.append(node("p", "", stats.days + " 天 · " + stats.stops + " 站 · 转场 " + routeTime.duration(stats.transfer_min)));
    for (const arrival of stats.arrivals || []) {
      card.append(node("p", "", "第 " + arrival.day + " 天预计 " + routeTime.arrival(arrival.arrival, arrival.deadline) + " 到" + arrival.destination + " · 最晚 " + routeTime.exact(arrival.deadline)));
    }
    container.append(card);
  }
  const text = node("div", "comparison-text");
  paragraphs(text, result.answer);
  const details = node("details", "answer-detail");
  details.append(node("summary", "", "查看景点差异与完整对比"), text);
  container.append(details);
  return container;
}
function comparisonIsOutdated(result) {
  var _a2;
  return (result == null ? void 0 : result.outdated) || ((_a2 = result == null ? void 0 : result.versions) == null ? void 0 : _a2.some((version) => state.plans.some((p) => p.id === version.option_id && p.version > version.version)));
}
function currentComparison() {
  var _a2;
  const result = state.comparison;
  return (result == null ? void 0 : result.status) === "passed" && ((_a2 = result.versions) == null ? void 0 : _a2.length) && !comparisonIsOutdated(result) ? result : null;
}
function updateMapLink() {
  const url = selectedPlan ? "/routes?" + new URLSearchParams({ plan: selectedPlan, day: openDay }) : "/routes";
  const city = url.replace("/routes", "/city");
  for (const link2 of [get("city-plan-link"), get("board-map-open")]) if (link2) link2.href = city;
  for (const link2 of [get("jump-map"), document.querySelector(".nav-map")]) if (link2) link2.href = url;
}
let boardMap = null, boardLayer = null, boardKey = "";
async function drawBoardMap() {
  var _a2, _b2, _c2, _d2, _e2;
  const box = get("board-map");
  const plan = state.plans.find((p) => p.id === selectedPlan);
  const card = ((_a2 = plan == null ? void 0 : plan.cards) == null ? void 0 : _a2[openDay]) || plan && Object.values(plan.cards)[0];
  if (!box || !card || activeTab !== "plans" || typeof WuhanMap === "undefined") {
    if (box) box.hidden = true;
    return;
  }
  box.hidden = false;
  const day = plan.cards[openDay] ? openDay : Object.keys(plan.cards)[0];
  get("board-map-label").textContent = "第 " + day + " 天路线 · " + (((_c2 = (_b2 = card.audit) == null ? void 0 : _b2.stops) == null ? void 0 : _c2.length) || 0) + " 站";
  get("board-map-open").href = "/city?" + new URLSearchParams({ plan: plan.id, day });
  if (!routePoints) routePoints = await WuhanMap.readJSON("/route-points").catch(() => ({}));
  if (!boardMap) {
    boardMap = WuhanMap.create("board-map-canvas");
    boardLayer = L.layerGroup().addTo(boardMap);
  }
  boardMap.invalidateSize();
  const key = [plan.id, plan.version, day, (((_d2 = card.audit) == null ? void 0 : _d2.stops) || []).map((s) => s.place + s.start).join()].join("|");
  if (key === boardKey) return;
  boardKey = key;
  boardLayer.clearLayers();
  const stops = WuhanMap.stops(card, routePoints).filter((stop) => stop.coords);
  const svg = L.svg({ padding: 0.2 });
  for (let i = 1; i < stops.length; i++) {
    L.polyline([stops[i - 1].coords, stops[i].coords], { renderer: svg, interactive: false, color: "#fff8dd", weight: 7, opacity: 0.95 }).addTo(boardLayer);
    const leg = L.polyline([stops[i - 1].coords, stops[i].coords], { renderer: svg, interactive: false, color: "#e8562d", weight: 3.5, className: "board-leg" }).addTo(boardLayer);
    (_e2 = leg.getElement()) == null ? void 0 : _e2.style.setProperty("--delay", i * 0.28 + "s");
  }
  stops.forEach((stop, i) => {
    const icon = L.divIcon({ className: "atlas-step board-step", html: '<span style="animation-delay:' + i * 0.28 + 's">' + (i + 1) + "</span>", iconSize: [26, 26], iconAnchor: [13, 13] });
    L.marker(stop.coords, { icon, title: i + 1 + " · " + stop.name, keyboard: false }).bindTooltip(stop.name + " · " + stop.time, { direction: "top", offset: [0, -12] }).addTo(boardLayer);
  });
  if (stops.length) boardMap.fitBounds(L.latLngBounds(stops.map((s) => s.coords)), { paddingTopLeft: [26, 26], paddingBottomRight: [26, 46], maxZoom: 14.2, animate: false });
}
const hm = (minute) => String(Math.floor(minute / 60)).padStart(2, "0") + ":" + String(minute % 60).padStart(2, "0");
function takeawayPlan() {
  return state.plans.find((plan) => plan.id === selectedPlan) || state.plans.find((plan) => plan.id === "current") || state.plans[0];
}
function tripText(plan) {
  return Object.keys(plan.cards).sort((a, b) => a - b).map((day) => {
    var _a2, _b2;
    const card = plan.cards[day], stops = ((_a2 = card.audit) == null ? void 0 : _a2.stops) || [];
    if (!stops.length) return "第".concat(day, "天：自由活动");
    const back = ((_b2 = card.contract) == null ? void 0 : _b2.destination) ? "，约 ".concat(hm(card.audit.arrival), " 回到").concat(card.contract.destination) : "";
    const c = card.contract;
    const origin = (c == null ? void 0 : c.origin) && c.origin !== stops[0].place ? hm(c.start) + " " + c.origin + "出发 → " : "";
    return "第".concat(day, "天：") + origin + stops.map((s) => "".concat(hm(s.start), " ").concat(s.place)).join(" → ") + back;
  }).join("\n") + "\n—— 武汉接线台 · 江豚接待员排程（时间为估算，出发前核实开放与预约）";
}
function tripCalendar(plan, firstDay) {
  var _a2, _b2;
  const stamp = (/* @__PURE__ */ new Date()).toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");
  const esc = (text) => String(text).replace(/[\\;,]/g, (m) => "\\" + m).replace(/\n/g, "\\n");
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SAIG//Wuhan Switchboard//ZH", "CALSCALE:GREGORIAN", "X-WR-CALNAME:武汉行程"];
  for (const day of Object.keys(plan.cards).sort((a, b) => a - b)) {
    const date = new Date(firstDay.getTime() + (day - 1) * 864e5);
    const ymd = date.getFullYear() + String(date.getMonth() + 1).padStart(2, "0") + String(date.getDate()).padStart(2, "0");
    for (const [i, stop] of (((_a2 = plan.cards[day].audit) == null ? void 0 : _a2.stops) || []).entries()) {
      const t = (minute) => ymd + "T" + hm(minute).replace(":", "") + "00";
      lines.push(
        "BEGIN:VEVENT",
        "UID:saig-".concat(ymd, "-").concat(day, "-").concat(i, "-").concat(stamp, "@wuhan-switchboard"),
        "DTSTAMP:" + stamp,
        "DTSTART:" + t(stop.start),
        "DTEND:" + t((_b2 = stop.end) != null ? _b2 : stop.start + 60),
        "SUMMARY:" + esc(stop.place),
        "LOCATION:" + esc("武汉 " + stop.place),
        "DESCRIPTION:" + esc("第".concat(day, "天第").concat(i + 1, "站 · 导航：https://uri.amap.com/search?keyword=").concat(stop.place, "&city=武汉")),
        "END:VEVENT"
      );
    }
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}
const exportMenu = get("trip-takeaway");
document.addEventListener("click", (event) => {
  if ((exportMenu == null ? void 0 : exportMenu.open) && !exportMenu.contains(event.target)) exportMenu.open = false;
});
for (const id of ["trip-amap", "trip-ics"]) (_d = get(id)) == null ? void 0 : _d.addEventListener("click", () => {
  exportMenu.open = false;
});
function renderTakeaway() {
  var _a2, _b2;
  const bar = get("trip-takeaway"), plan = takeawayPlan();
  if (!bar) return;
  bar.hidden = !plan || !Object.keys(plan.cards || {}).length;
  const input = get("trip-date");
  const fixed = plan && ((_b2 = (_a2 = Object.values(plan.cards || {})[0]) == null ? void 0 : _a2.contract) == null ? void 0 : _b2.date);
  const tomorrow = new Date(Date.now() + 864e5);
  input.value = fixed || tomorrow.getFullYear() + "-" + String(tomorrow.getMonth() + 1).padStart(2, "0") + "-" + String(tomorrow.getDate()).padStart(2, "0");
  get("trip-ics").title = "第 1 天按 " + input.value + " 加入日历（告诉江豚出发日期可改）";
}
(_e = get("trip-ics")) == null ? void 0 : _e.addEventListener("click", () => {
  const plan = takeawayPlan();
  if (!plan) return;
  const [y, m, d] = (get("trip-date").value || "").split("-").map(Number);
  const first = y ? new Date(y, m - 1, d) : new Date(Date.now() + 864e5);
  const link2 = document.createElement("a");
  link2.href = URL.createObjectURL(new Blob([tripCalendar(plan, first)], { type: "text/calendar;charset=utf-8" }));
  link2.download = "武汉行程.ics";
  document.body.append(link2);
  link2.click();
  link2.remove();
  setTimeout(() => URL.revokeObjectURL(link2.href), 4e3);
});
function askNowPlan(place) {
  if (place) return sendText("我现在在".concat(place, "附近，接下来 3 小时怎么安排？"));
  const template = "我现在在附近，接下来 3 小时怎么安排？";
  question.value = template;
  resizeInput();
  question.focus();
  const at = template.indexOf("附近");
  question.setSelectionRange(at, at);
  get("progress").textContent = "先填上你现在所在的地铁站或地标";
}
async function startNowPlan() {
  if (state.pending) return;
  if (!window.isSecureContext || !navigator.geolocation) return askNowPlan();
  get("progress").textContent = "正在获取你的位置…";
  if (!routePoints) routePoints = await WuhanMap.readJSON("/route-points").catch(() => ({}));
  navigator.geolocation.getCurrentPosition((pos) => {
    const { latitude: lat, longitude: lon } = pos.coords;
    let best = null;
    for (const [name, p] of Object.entries(routePoints || {})) {
      if (!Number.isFinite(p == null ? void 0 : p.lat)) continue;
      const d = Math.hypot((p.lat - lat) * 111, (p.lon - lon) * 96);
      if (!best || d < best.d) best = { name, d };
    }
    get("progress").textContent = "";
    askNowPlan(best && best.d < 6 ? best.name : null);
  }, () => askNowPlan(), { timeout: 8e3, maximumAge: 3e5 });
}
for (const el of document.querySelectorAll("[data-now-plan]")) el.addEventListener("click", startNowPlan);
(_f = get("trip-amap")) == null ? void 0 : _f.addEventListener("click", async () => {
  const plan = takeawayPlan();
  if (!plan) return;
  if (!routePoints) routePoints = await WuhanMap.readJSON("/route-points").catch(() => ({}));
  const day = plan.cards[openDay] ? openDay : Object.keys(plan.cards).sort((a, b) => a - b)[0];
  const url = Amap.day(plan.cards[day]);
  if (url) window.open(url, "_blank", "noopener");
});
(_g = get("trip-copy")) == null ? void 0 : _g.addEventListener("click", async () => {
  const plan = takeawayPlan(), button2 = get("trip-copy");
  if (!plan) return;
  const text = tripText(plan);
  const label = button2.querySelector("span");
  try {
    await navigator.clipboard.writeText(text);
    label.textContent = "已复制";
  } catch {
    window.prompt("复制下面的行程：", text);
  }
  setTimeout(() => {
    label.textContent = "复制文字";
    exportMenu.open = false;
  }, 1200);
});
function renderBoard() {
  updateMapLink();
  renderTakeaway();
  drawBoardMap();
  get("board-summary").textContent = state.plans.length ? "可以继续跟江豚说怎么改" : "排好的行程会出现在这里";
  get("jump-map").hidden = !state.plans.length;
  const comparable = state.comparison || state.plans.filter((p) => p.id !== "preview").length > 1;
  get("board-tabs").hidden = !comparable;
  if (!comparable && !get("comparison").hidden) showTab("plans");
  const plans = get("plans");
  if (!state.plans.length) {
    plans.replaceChildren(emptyBoard("还没有行程", "跟江豚说玩几天、住哪里，比如「帮我排两天，住江汉路」。"));
  } else {
    const grid = node("div", "plan-grid");
    grid.append(...state.plans.map(planCard));
    plans.replaceChildren(grid);
  }
  const comparison = get("comparison");
  const result = state.comparison;
  const outdated = comparisonIsOutdated(result);
  if (result && !outdated && result.status === "passed") comparison.replaceChildren(comparisonView(result));
  else {
    const title = outdated ? "行程已有新版本" : result ? "比较尚未完成" : "还没有比较结果";
    const copy = outdated ? "重新比较即可查看更新后的路线差异。" : result ? result.answer : "请接待员比较两份方案，就能看到景点、节奏和转场差异。";
    comparison.replaceChildren(emptyBoard(title, copy, state.plans.length >= 2 ? { label: "发起比较 ↗", click: compareAgain } : null));
  }
  get("save-comparison").hidden = activeTab !== "comparison" || !currentComparison();
}
function dayChanged(before, after) {
  var _a2, _b2, _c2, _d2;
  if (!before || !after) return false;
  const a = (((_a2 = before.audit) == null ? void 0 : _a2.stops) || []).map((s) => s.place + s.start).join(), b = (((_b2 = after.audit) == null ? void 0 : _b2.stops) || []).map((s) => s.place + s.start).join();
  return a !== b || ((_c2 = before.audit) == null ? void 0 : _c2.arrival) !== ((_d2 = after.audit) == null ? void 0 : _d2.arrival);
}
function putPlan(id, title, cards, version, replannedDays = [], beforeCounts = {}) {
  const index = state.plans.findIndex((plan2) => plan2.id === id);
  const old = index < 0 ? null : state.plans[index];
  const changed = old ? Object.keys(cards).filter((day) => {
    var _a2;
    return dayChanged((_a2 = old.cards) == null ? void 0 : _a2[day], cards[day]);
  }) : [];
  const previous = changed.length ? old.cards : (old == null ? void 0 : old.previous) || null;
  const changedDays = changed.length ? changed : (old == null ? void 0 : old.changedDays) || [];
  if (changed.length && !replannedDays.length) replannedDays = changed;
  const plan = { id, title, cards, version: changed.length && version <= ((old == null ? void 0 : old.version) || 0) ? old.version + 1 : version, replannedDays, beforeCounts, previous, changedDays };
  if (index < 0) state.plans.push(plan);
  else state.plans[index] = plan;
}
function updateBoard(result) {
  var _a2, _b2, _c2, _d2;
  for (const item of result.deliverables || []) {
    if (item.kind === "compare") state.comparison = item;
    if (item.status !== "passed" || !item.cards || !item.option_id || !["plan", "revise"].includes(item.kind)) continue;
    const previous = state.plans.find((plan) => plan.id === item.option_id);
    const beforeCounts = (item.replanned_days || []).reduce((counts, day) => {
      var _a3, _b3, _c3, _d3;
      counts[day] = (_d3 = (_c3 = (_b3 = (_a3 = previous == null ? void 0 : previous.cards) == null ? void 0 : _a3[day]) == null ? void 0 : _b3.audit) == null ? void 0 : _c3.stops) == null ? void 0 : _d3.length;
      return counts;
    }, {});
    putPlan(item.option_id, (previous == null ? void 0 : previous.title) || item.title, item.cards, item.version || 1, item.replanned_days, beforeCounts);
    if (!selectedPlan || item.kind === "revise") {
      selectedPlan = item.option_id;
      openDay = String(((_a2 = item.replanned_days) == null ? void 0 : _a2[0]) || 1);
    }
  }
  if (Object.keys(result.days || {}).length && !((_b2 = result.deliverables) == null ? void 0 : _b2.some((item) => item.status === "passed" && item.option_id === "current"))) {
    putPlan("current", "正式行程", result.days, 1);
    const current = state.plans.find((plan) => plan.id === "current");
    if (((_c2 = current == null ? void 0 : current.replannedDays) == null ? void 0 : _c2.length) && current.previous) {
      selectedPlan = "current";
      openDay = String(current.replannedDays[0]);
    }
  }
  if (Object.keys(result.preview || {}).length) {
    putPlan("preview", result.preview_title || "试排方案", result.preview, 1);
    if (result.preview_title) {
      selectedPlan = "preview";
      openDay = "1";
    }
  }
  if (result.mode === "plan" || result.mode === "edit") state.plans = state.plans.filter((plan) => plan.id !== "preview");
  if ((_d2 = result.deliverables) == null ? void 0 : _d2.some((item) => item.kind === "adopt" && item.status === "passed")) {
    showTab("plans");
    selectedPlan = "current";
  }
  if (state.plans.length && !state.plans.some((plan) => plan.id === selectedPlan)) selectedPlan = state.plans[0].id;
}
function resizeInput() {
  question.style.height = "43px";
  question.style.height = Math.min(132, Math.max(43, question.scrollHeight)) + "px";
}
function fill(text) {
  question.value = text;
  resizeInput();
  question.focus({ preventScroll: true });
  question.scrollIntoView({ block: "nearest" });
}
function syncInputs() {
  get("send").disabled = !!state.pending;
  get("reset").disabled = busy;
}
function renderFollowups() {
  var _a2, _b2;
  const el = get("followups");
  el.replaceChildren();
  el.hidden = !!state.pending || !state.messages.length;
  if (el.hidden) return;
  const hasTwoDayPlan = state.plans.some((plan) => plan.id !== "current" && Object.keys(plan.cards).length === 2);
  if (!state.plans.length) el.append(button("chip", "规划并比较行程", () => fill(planPrompt)));
  if (hasTwoDayPlan && !((_b2 = (_a2 = currentReply()) == null ? void 0 : _a2.deliverables) == null ? void 0 : _b2.some((item) => item.kind === "revise"))) {
    el.append(button("chip", "调整两日游第 2 天", () => fill("两日游第二天想轻松点，下午四点要到汉口站。一日游照旧，再帮我比较一下。")));
  }
  el.append(
    button("chip", "问数命 SPU 社区", () => fill(document.querySelector(".skill[data-skill='community']").dataset.prompt)),
    button("chip", "问 SAIG 参赛", () => fill(document.querySelector(".skill[data-skill='saig']").dataset.prompt))
  );
  if (state.plans.length && el.children.length < 4) el.append(button("chip", "临时安排：接下来 3 小时", startNowPlan));
}
function render() {
  renderMessages();
  renderBoard();
  renderFollowups();
  syncInputs();
}
async function sendText(text) {
  const value = text.trim();
  if (!value || state.pending) return;
  state.messages.push({ role: "user", text: value });
  state.pending = { text: value, id: newId() };
  question.value = "";
  resizeInput();
  save();
  await sendPending();
}
const stepLabel = (name, args = {}) => ({
  search_knowledge: "检索官方资料" + (args.query ? "：" + args.query : ""),
  read_source: "读原文",
  find_place: "查地点" + (args.name ? "：" + args.name : ""),
  get_trip: "读取当前行程",
  plan_trip: "排行程（计算交通与时间）",
  edit_trip: "调整第 " + (args.day || "?") + " 天行程",
  append_day: "新增第 " + args.day + " 天",
  append_stops: "接着安排第 " + args.day + " 天后续行程",
  read_skill: "翻看接待手册",
  remember: "记下你的信息",
  get_weather: "查看武汉天气",
  arrival_guide: "查接站路线" + (args.gateway ? "：" + args.gateway : "")
})[name] || name;
function liveStep(name, args) {
  const steps = get("work-steps");
  if (!steps) return null;
  if (steps.dataset.mode !== "live") {
    steps.replaceChildren();
    steps.dataset.mode = "live";
  }
  const item = node("li", "active", stepLabel(name, args));
  steps.append(item);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return item;
}
function liveText(text) {
  var _a2;
  let box = get("live-text");
  const bubble = (_a2 = get("work-steps")) == null ? void 0 : _a2.parentElement;
  if (!bubble) return;
  if (!box) {
    box = node("div", "live-text");
    box.id = "live-text";
    bubble.append(box);
  }
  box.textContent = text.replace(/\s*\[S\d+(?:[,，、\s]*S\d+)*\]/g, "");
  chatWindow.scrollTop = chatWindow.scrollHeight;
}
async function streamChat(payload) {
  var _a2, _b2;
  if (typeof ReadableStream === "undefined" || typeof TextDecoder === "undefined") return null;
  const response = await fetch("/chat/stream", { method: "POST", headers: apiHeaders(), body: JSON.stringify(payload) });
  if (!response.ok || !response.body) {
    const failed = await response.json().catch(() => ({}));
    throw new Error(failed.error || "暂时无法完成这次问答");
  }
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = "", result = null, text = "", current = null;
  for (; ; ) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const kind = (_a2 = /^event: (.*)$/m.exec(block)) == null ? void 0 : _a2[1], raw = (_b2 = /^data: (.*)$/m.exec(block)) == null ? void 0 : _b2[1];
      if (!kind || !raw) continue;
      const data = JSON.parse(raw);
      if (kind === "result") result = data;
      else if (kind === "error") throw new Error(data.error || "暂时无法完成这次问答");
      else if (kind === "tool") current = liveStep(data.name, data.args);
      else if (kind === "tool_done" && current) {
        current.className = data.ok ? "done" : "failed";
        current = null;
      } else if (kind === "step") text = "";
      else if (kind === "delta") {
        text += data.text;
        liveText(text);
        streamedReply = text.trim().length > 0;
      } else if (kind === "step_end" && !data.final) {
        text = "";
        liveText("");
        streamedReply = false;
      }
    }
  }
  if (!result) throw new TypeError("stream ended early");
  return result;
}
async function sendPending() {
  if (busy || !state.pending) return;
  const pending = state.pending;
  busy = true;
  render();
  const start = performance.now();
  const progress = get("progress");
  if (typeof Receptionist !== "undefined") {
    Receptionist.stop();
    Receptionist.set("thinking");
  }
  progress.textContent = "正在整理答复…";
  tickSteps(0);
  const timer = setInterval(() => {
    const elapsed = (performance.now() - start) / 1e3;
    progress.textContent = "正在整理答复… " + Math.floor(elapsed) + " 秒";
    tickSteps(elapsed);
  }, 250);
  try {
    streamedReply = false;
    const payload = { query: pending.text, session: state.session, request_id: pending.id };
    let result = await streamChat(payload);
    if (!result) {
      const response = await fetch("/chat", { method: "POST", headers: apiHeaders(), body: JSON.stringify(payload) });
      result = await response.json();
      if (!response.ok) throw new Error(result.error || "暂时无法完成这次问答");
    }
    state.session = result.session;
    state.messages.push({ role: "assistant", result: {
      answer: result.answer,
      summary_lines: result.summary_lines,
      citations: result.citations,
      deliverables: result.deliverables,
      topics: replyTopics(result)
    } });
    if (typeof Receptionist !== "undefined") Receptionist.say(spokenReply(result));
    updateBoard(result);
    animateReply = true;
    state.pending = null;
    setConnection("online");
    progress.textContent = "已回复 · " + ((performance.now() - start) / 1e3).toFixed(1) + " 秒";
  } catch (error) {
    state.pending.error = error instanceof TypeError ? "连接中断，点击重试继续这条消息。" : error.message;
    progress.textContent = "等待重试";
    if (typeof Receptionist !== "undefined") Receptionist.set("error");
    checkConnection();
  } finally {
    clearInterval(timer);
    busy = false;
    save();
    render();
    if (animateReply && !streamedReply) typeReply();
    animateReply = false;
    streamedReply = false;
  }
}
get("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  sendText(question.value);
});
question.addEventListener("input", resizeInput);
question.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendText(question.value);
  }
});
const DEMO_ROUTE = ["古琴台", "龟山公园", "武汉长江大桥", "黄鹤楼", "户部巷", "楚河汉街", "东湖听涛"];
function loadFlyover() {
  if (window.Flyover) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = "/web/flyover.js";
    tag.onload = resolve;
    tag.onerror = reject;
    document.head.append(tag);
  });
}
async function openFlyover(card, title) {
  var _a2, _b2, _c2, _d2;
  if (!routePoints) routePoints = await WuhanMap.readJSON("/route-points").catch(() => ({}));
  const pt = (name) => routePoints == null ? void 0 : routePoints[name];
  const stops = [];
  if (card) {
    const c = card.contract || {}, visits = ((_a2 = card.audit) == null ? void 0 : _a2.stops) || [], legs = ((_b2 = card.audit) == null ? void 0 : _b2.legs) || [];
    if (c.origin && c.origin !== ((_c2 = visits[0]) == null ? void 0 : _c2.place) && pt(c.origin)) stops.push({ name: c.origin, label: "起", kicker: hm(c.start) + " 出发", detail: "", say: "从".concat(c.origin, "出发。") });
    visits.forEach((s, i) => {
      const leg = legs.find((l) => l.destination === s.place && l.origin !== l.destination);
      const how = leg ? [modes[leg.mode], Number.isFinite(leg.minutes) ? "约 " + leg.minutes + " 分钟" : ""].filter(Boolean).join(" ") : "";
      if (pt(s.place)) stops.push({ name: s.place, label: i + 1, kicker: "第 ".concat(i + 1, " 站 · ").concat(hm(s.start), "–").concat(hm(s.end)), detail: how ? how + "到这里" : "", say: "第".concat(i + 1, "站，").concat(s.place, "。") });
    });
    if (c.destination && c.destination !== ((_d2 = stops[stops.length - 1]) == null ? void 0 : _d2.name) && pt(c.destination)) stops.push({ name: c.destination, label: "终", kind: "end", kicker: "约 " + hm(card.audit.arrival) + " 到达", detail: "", say: "最后到".concat(c.destination, "。") });
  } else {
    DEMO_ROUTE.forEach((name, i) => pt(name) && stops.push({ name, label: i + 1, kicker: "第 ".concat(i + 1, " 站"), detail: "", say: "".concat(name, "。") }));
  }
  for (const s of stops) {
    s.lat = pt(s.name).lat;
    s.lon = pt(s.name).lon;
  }
  if (stops.length < 2) return;
  try {
    await loadFlyover();
  } catch {
    return;
  }
  const say = typeof Receptionist !== "undefined" && Receptionist.say ? (text) => Receptionist.say(text) : null;
  window.Flyover.open({ stops, title, landmarks: typeof Landmarks !== "undefined" ? Landmarks.LIST : [], say });
}
(_h = get("fly-plan")) == null ? void 0 : _h.addEventListener("click", () => {
  const plan = takeawayPlan();
  if (!plan) return;
  const day = plan.cards[openDay] ? openDay : Object.keys(plan.cards).sort((a, b) => a - b)[0];
  openFlyover(plan.cards[day], "3D 飞览 · ".concat(plan.title || "行程", " 第 ").concat(day, " 天"));
});
(_i = get("fly-demo")) == null ? void 0 : _i.addEventListener("click", () => openFlyover(null, "3D 飞览武汉 · 经典一日"));
const tourButton = get("judge-tour");
if (tourButton) tourButton.addEventListener("click", async () => {
  if (state.pending || tourButton.disabled) return;
  const prompts = [...document.querySelectorAll(".starter.skill")].map((item) => item.dataset.prompt);
  prompts.push("第一天有点累，少两个点，下午一点再出发。");
  const label = tourButton.innerHTML;
  tourButton.disabled = true;
  get("assistant").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    for (const [index, prompt] of prompts.entries()) {
      tourButton.textContent = "演示中 ".concat(index + 1, "/").concat(prompts.length);
      await sendText(prompt);
      if (state.pending) break;
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
  } finally {
    tourButton.disabled = false;
    tourButton.innerHTML = label;
  }
  const plan = state.plans.find((p) => p.id === "current");
  if (plan && !state.pending) openFlyover(plan.cards["1"], "3D 飞览 · 刚排好的第 1 天");
});
for (const starter of document.querySelectorAll(".starter")) {
  starter.addEventListener("click", () => {
    if (starter.classList.contains("skill")) get("assistant").scrollIntoView({ behavior: "smooth", block: "start" });
    sendText(starter.dataset.prompt);
  });
}
const exportButton = get("save-comparison");
exportButton.addEventListener("click", async () => {
  const result = currentComparison();
  if (!result) return;
  const rows = [].concat(...result.versions.map((version) => {
    var _a2, _b2;
    const stats = (_a2 = result.metrics) == null ? void 0 : _a2[version.input];
    if (!stats) return [];
    const plan = state.plans.find((item) => item.id === version.option_id);
    const arrivals = (stats.arrivals || []).map((arrival) => "第 " + arrival.day + " 天预计 " + routeTime.arrival(arrival.arrival, arrival.deadline) + " 到" + arrival.destination + "，最晚 " + routeTime.exact(arrival.deadline));
    const changedDay = (_b2 = plan == null ? void 0 : plan.replannedDays) == null ? void 0 : _b2.find((day) => {
      var _a3;
      return Number.isInteger((_a3 = plan.beforeCounts) == null ? void 0 : _a3[day]) && plan.beforeCounts[day] !== stats.daily_stops[day - 1];
    });
    const change = changedDay ? "临时改口后，第 " + changedDay + " 天从 " + plan.beforeCounts[changedDay] + " 站改成 " + stats.daily_stops[changedDay - 1] + " 站" : "";
    return [{ title: (plan == null ? void 0 : plan.title) || stats.days + " 天游览方案", stats, arrivals, change }];
  }));
  exportButton.disabled = true;
  exportButton.textContent = "正在生成…";
  try {
    await downloadComparisonPoster(rows);
    exportButton.textContent = "保存对比图 ↓";
  } catch {
    exportButton.textContent = "生成失败，重试";
  } finally {
    exportButton.disabled = false;
  }
});
const resetDialog = get("reset-dialog");
get("reset").addEventListener("click", () => {
  if (!state.messages.length) return fill("");
  resetDialog.returnValue = "cancel";
  if (typeof resetDialog.showModal === "function") resetDialog.showModal();
  else if (window.confirm("删除本次对话、行程和人物记录并重新开始？")) clearSession();
});
resetDialog.addEventListener("close", () => {
  if (resetDialog.returnValue === "reset") clearSession();
});
async function clearSession() {
  if (busy) return;
  busy = true;
  render();
  try {
    const response = await fetch("/session/delete", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ session: state.session })
    });
    if (!response.ok) throw new Error("delete failed");
  } catch {
    get("progress").textContent = "删除未完成，请重新连接后重试。";
    return;
  } finally {
    busy = false;
    render();
  }
  state = defaultState();
  selectedPlan = "";
  get("progress").textContent = "";
  save();
  showTab("plans");
  render();
  fill("");
}
for (const [tab, id] of [["plans", "plans-tab"], ["comparison", "comparison-tab"]]) {
  get(id).addEventListener("click", () => showTab(tab));
  get(id).addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "plans" : event.key === "End" ? "comparison" : activeTab === "plans" ? "comparison" : "plans";
    showTab(next, true);
  });
}
window.addEventListener("pageshow", (event) => {
  var _a2, _b2, _c2;
  if (!event.persisted) return;
  state = restore();
  selectedPlan = ((_a2 = state.mapSelection) == null ? void 0 : _a2.plan) || ((_b2 = state.plans[0]) == null ? void 0 : _b2.id) || "";
  openDay = ((_c2 = state.mapSelection) == null ? void 0 : _c2.day) || "1";
  render();
});
render();
