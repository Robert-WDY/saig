"use strict";

const get = id => document.getElementById(id);
const question = get("question");
const chatWindow = get("chat-window");
const messages = get("messages");
const planPrompt = document.querySelector(".starter[data-prompt*='一日游']").dataset.prompt;
const storageKey = "saig-visitor-workspace-v1";
const modes = {walk: "步行", metro: "地铁", transit: "公共交通", taxi: "打车", estimate: "转场"};
const defaultState = () => ({session: newId(), messages: [], plans: [], comparison: null, pending: null});
let state = restore();
let busy = false;
let activeTab = "plans";
let selectedPlan = state.plans[0]?.id || "";
let openDay = "1";
let animateReply = false;

function restore() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey));
    if (saved?.session && Array.isArray(saved.messages) && Array.isArray(saved.plans)) return saved;
  } catch {
    // A fresh session also works when browser storage is unavailable.
  }
  return defaultState();
}

function save() {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(state));
  } catch {
    // Keep running in memory if storage is full or disabled.
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

function paragraphs(parent, text = "") {
  for (const line of text.trim().split(/\r?\n/)) {
    if (!line.trim()) continue;
    const p = node("p", /^\s*第\d+天/.test(line) ? "route-snippet" : "");
    const tokens = line.replace(/^\s*#{1,6}\s+/, "").split(/(https?:\/\/[^\s，。；、）]+|\*\*[^*]+\*\*)/g);
    for (const token of tokens) {
      if (token.startsWith("**") && token.endsWith("**")) p.append(node("strong", "", token.slice(2, -2)));
      else if (/^https?:\/\//.test(token)) p.append(link(token, token) || document.createTextNode(token));
      else p.append(document.createTextNode(token));
    }
    parent.append(p);
  }
}

function currentReply() {
  return lastWhere(state.messages, message => message.role === "assistant")?.result;
}

function setConnection(status) {
  const el = get("connection");
  const labels = {online: "接待员在线", offline: "暂时离线"};
  el.className = "connection " + status;
  el.replaceChildren(node("i"), document.createTextNode(labels[status]));
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

function showTab(tab, focus = false) {
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
  if (id && state.plans.some(plan => plan.id === id)) {
    selectedPlan = id;
    openDay = String(days?.[0] || 1);
    renderBoard();
  }
  showTab(tab);
  get("workspace").scrollIntoView({block: "nearest"});
  get(tab === "plans" ? "plans-tab" : "comparison-tab").focus({preventScroll: true});
}

function viewDeliverable(delivery) {
  if (delivery.kind === "compare") revealBoard("comparison");
  else {
    const id = delivery.kind === "adopt" ? "current" : delivery.option_id || delivery.inputs?.[0];
    revealBoard("plans", id, delivery.replanned_days);
  }
}

function appendSources(parent, citations = []) {
  const sources = new Map();
  for (const citation of citations) {
    const title = citation.title || "来源";
    const label = citation.locator && /^\d+$/.test(citation.locator) ? title + " · 第" + citation.locator + "页" : title;
    const a = link(label + " ↗", citation.source, "source");
    if (a) sources.set(label + citation.source, a);
  }
  if (!sources.size) return;
  const details = node("details", "sources");
  const list = node("div", "source-list");
  list.append(...sources.values());
  details.append(node("summary", "", "查看资料出处（" + sources.size + "）"), list);
  parent.append(details);
}

function renderReply(bubble, result) {
  const deliveries = result.deliverables || [];
  const visibleCards = deliveries.filter(d => d.status === "passed" && (d.cards || d.kind === "compare"));
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
    for (const item of deliveries.filter(d => !visibleCards.includes(d))) {
      if (item.status === "passed") paragraphs(list, item.answer);
      else list.append(node("p", "failed", item.title + " · " + item.answer));
    }
    bubble.append(list);
    const details = node("details", "answer-detail");
    details.append(node("summary", "", "展开完整回答"), body);
    bubble.append(details);
  } else {
    bubble.append(body);
  }
  paragraphs(body, result.answer);
  appendSources(bubble, result.citations);
}

function renderMessages() {
  get("welcome").hidden = state.messages.length > 0;
  const fragment = document.createDocumentFragment();
  for (const message of state.messages) {
    const entry = node("article", "message " + message.role);
    if (animateReply && message === state.messages[state.messages.length - 1] && message.role === "assistant") entry.classList.add("reply-in");
    const bubble = node("div", "bubble");
    if (message.role === "user") bubble.textContent = message.text;
    else {
      const mark = node("span", "mark", "接");
      mark.setAttribute("aria-hidden", "true");
      entry.append(mark);
      bubble.setAttribute("aria-label", "接待员的回答");
      renderReply(bubble, message.result);
    }
    entry.append(bubble);
    fragment.append(entry);
  }
  if (state.pending) {
    const entry = node("div", busy ? "message" : "message error");
    const bubble = node("div", "bubble");
    if (busy) bubble.append(node("p", "working", "接待员正在整理答复…"));
    else {
      bubble.append(node("p", "", state.pending.error || "这条消息还在等答复。"));
      bubble.append(button("chip", "重试发送", () => sendPending()));
    }
    entry.append(bubble);
    fragment.append(entry);
  }
  messages.replaceChildren(fragment);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function stopRow(name, time, leg, arrival = false, exact = "") {
  const row = node("li", arrival ? "arrival" : "");
  const clock = node("time", "", time);
  if (exact) clock.title = "计划原值 " + exact;
  row.append(clock, node("span", "", name));
  if (leg) {
    const description = [modes[leg.mode], Number.isFinite(leg.minutes) ? routeTime.duration(leg.minutes) : "", leg.directions].filter(Boolean).join(" · ");
    row.append(node("span", "leg", description));
  }
  return row;
}

function daySection(number, day, open) {
  const details = node("details", "day-card");
  details.open = open;
  const stops = day.audit?.stops || [];
  const summary = node("summary", "", "第 " + number + " 天");
  summary.append(node("small", "", stops.length + " 站"));
  const list = node("ol", "stops");
  const contract = day.contract || {};
  const legs = day.audit?.legs || [];
  if (contract.origin && contract.origin !== stops[0]?.place) {
    list.append(stopRow(contract.origin + "出发", routeTime.exact(contract.start)));
  }
  for (const stop of stops) {
    const leg = legs.find(item => item.destination === stop.place && item.origin !== item.destination);
    list.append(stopRow(stop.place, routeTime.stop(stop, contract), leg, false,
      routeTime.exact(stop.start) + "–" + routeTime.exact(stop.end)));
  }
  if (contract.destination) {
    const limit = contract.end - (contract.buffer || 0);
    const arrival = routeTime.arrival(day.audit?.arrival, limit);
    list.append(stopRow("预计抵达 " + contract.destination + " · 最晚 " + routeTime.exact(limit), arrival,
      lastWhere(legs, item => item.destination === contract.destination), true, routeTime.exact(day.audit?.arrival)));
  }
  details.append(summary, list);
  if (day.guide_source) {
    const guide = link("参考 · " + day.guide_source.title + " ↗", day.guide_source.source, "guide");
    if (guide) details.append(guide);
  }
  return details;
}

function planCard(plan) {
  const selected = selectedPlan === plan.id;
  const card = node("article", selected ? "plan selected" : "plan");
  const heading = button("plan-header", "", () => {
    selectedPlan = selected ? "" : plan.id;
    openDay = String(plan.replannedDays?.[0] || 1);
    const top = get("plans").scrollTop;
    renderBoard();
    get("plans").scrollTop = top;
    document.getElementById(heading.id)?.focus({preventScroll: true});
  });
  heading.id = "plan-toggle-" + plan.id;
  heading.setAttribute("aria-expanded", selected);
  const meta = Object.keys(plan.cards).length + " 天" + (plan.version > 1 ? " · v" + plan.version : "");
  heading.append(node("span", "plan-title", plan.title), node("span", "plan-meta", meta));
  card.append(heading);
  if (!selected) return card;
  const content = node("div", "plan-content");
  if (plan.replannedDays?.length) {
    const summary = node("div", animateReply ? "plan-note plan-flash" : "plan-note");
    summary.append(node("p", "", "本轮更新第 " + plan.replannedDays.join("、") + " 天"));
    for (const day of plan.replannedDays) {
      const card = plan.cards[day];
      const contract = card?.contract;
      const before = plan.beforeCounts?.[day];
      const after = card?.audit?.stops?.length;
      if (Number.isInteger(before) && Number.isInteger(after) && before !== after) {
        summary.append(node("p", "stop-change", before + " 站 → " + after + " 站"));
      }
      if (!contract?.destination) continue;
      const limit = contract.end - (contract.buffer || 0);
      summary.append(node("p", "", "预计 " + routeTime.arrival(card.audit?.arrival, limit) + " 到" + contract.destination + " · 最晚 " + routeTime.exact(limit)));
    }
    content.append(summary);
  }
  for (const [day, details] of Object.entries(plan.cards)) {
    const section = daySection(day, details, day === openDay);
    section.addEventListener("toggle", () => {
      if (section.isConnected && section.open) {
        openDay = day;
        updateMapLink();
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
  if (action) el.append(button("text-button", action.label, action.click));
  return el;
}

function compareAgain() {
  const candidates = state.plans.filter(plan => plan.id !== "current" && plan.id !== "preview");
  if (candidates.length === 2) fill("请比较「" + candidates[0].title + "」和「" + candidates[1].title + "」的最新方案。");
  else fill("请比较这两份行程：");
}

function comparisonView(result) {
  const container = node("div", "comparison-body");
  for (const version of result.versions || []) {
    const plan = state.plans.find(p => p.id === version.option_id);
    const stats = result.metrics?.[version.input];
    if (!stats) continue;
    const card = node("section", "comparison-card");
    const title = plan?.title || "行程方案";
    card.append(node("h3", "", title + (version.version > 1 ? " · v" + version.version : "")));
    card.append(node("p", "", stats.days + " 天 · " + stats.stops + " 站 · 转场 " + routeTime.duration(stats.transfer_min)));
    for (const arrival of stats.arrivals || []) {
      card.append(node("p", "", "第 " + arrival.day + " 天预计 " + routeTime.arrival(arrival.arrival, arrival.deadline) +
        " 到" + arrival.destination + " · 最晚 " + routeTime.exact(arrival.deadline)));
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
  return result?.versions?.some(version => state.plans.some(p => p.id === version.option_id && p.version > version.version));
}

function currentComparison() {
  const result = state.comparison;
  return result?.status === "passed" && result.versions?.length && !comparisonIsOutdated(result) ? result : null;
}

function updateMapLink() {
  const url = selectedPlan ? "/routes?" + new URLSearchParams({plan: selectedPlan, day: openDay}) : "/routes";
  for (const link of [get("jump-map"), document.querySelector(".nav-map")]) link.href = url;
}

function renderBoard() {
  updateMapLink();
  get("board-summary").textContent = state.plans.length ? state.plans.length + " 份行程 · 可继续追问修改" : "查看路线和方案差异";
  const plans = get("plans");
  if (!state.plans.length) {
    plans.replaceChildren(emptyBoard("行程会显示在这里", "告诉接待员你有几天、想去哪里，就可以开始排路线。", {
      label: "生成并比较方案 ↗", click: () => sendText(planPrompt)
    }));
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
    comparison.replaceChildren(emptyBoard(title, copy, state.plans.length >= 2 ? {label: "发起比较 ↗", click: compareAgain} : null));
  }
  get("save-comparison").hidden = activeTab !== "comparison" || !currentComparison();
}

function putPlan(id, title, cards, version, replannedDays = [], beforeCounts = {}) {
  const index = state.plans.findIndex(plan => plan.id === id);
  const plan = {id, title, cards, version, replannedDays, beforeCounts};
  if (index < 0) state.plans.push(plan);
  else state.plans[index] = plan;
}

function updateBoard(result) {
  for (const item of result.deliverables || []) {
    if (item.kind === "compare") state.comparison = item;
    if (item.status !== "passed" || !item.cards || !item.option_id || !["plan", "revise"].includes(item.kind)) continue;
    const previous = state.plans.find(plan => plan.id === item.option_id);
    const beforeCounts = (item.replanned_days || []).reduce((counts, day) => { counts[day] = previous?.cards?.[day]?.audit?.stops?.length; return counts; }, {});
    putPlan(item.option_id, previous?.title || item.title, item.cards, item.version || 1, item.replanned_days, beforeCounts);
    if (!selectedPlan || item.kind === "revise") {
      selectedPlan = item.option_id;
      openDay = String(item.replanned_days?.[0] || 1);
    }
  }
  if (Object.keys(result.days || {}).length && !result.deliverables?.some(item => item.status === "passed" && item.option_id === "current")) {
    putPlan("current", "正式行程", result.days, 1);
  }
  if (Object.keys(result.preview || {}).length) putPlan("preview", "试排方案", result.preview, 1);
  if (result.mode === "plan" || result.mode === "edit") state.plans = state.plans.filter(plan => plan.id !== "preview");
  if (result.deliverables?.some(item => item.kind === "adopt" && item.status === "passed")) {
    showTab("plans");
    selectedPlan = "current";
  }
  if (state.plans.length && !state.plans.some(plan => plan.id === selectedPlan)) selectedPlan = state.plans[0].id;
}

function resizeInput() {
  question.style.height = "43px";
  question.style.height = Math.min(132, Math.max(43, question.scrollHeight)) + "px";
}

function fill(text) {
  question.value = text;
  resizeInput();
  question.focus({preventScroll: true});
  question.scrollIntoView({block: "nearest"});
}

function syncInputs() {
  get("send").disabled = !!state.pending;
  get("reset").disabled = busy;
}

function renderFollowups() {
  const el = get("followups");
  el.replaceChildren();
  el.hidden = !!state.pending || !state.messages.length;
  if (el.hidden) return;
  const hasTwoDayPlan = state.plans.some(plan => plan.id !== "current" && Object.keys(plan.cards).length === 2);
  if (!state.plans.length) el.append(button("chip", "规划并比较行程 ↗", () => fill(planPrompt)));
  if (hasTwoDayPlan && !currentReply()?.deliverables?.some(item => item.kind === "revise")) {
    el.append(button("chip", "调整两日游第 2 天 ↗", () => fill("两日游第二天想轻松点，下午四点要到汉口站。一日游照旧，再帮我比较一下。")));
  }
  el.append(
    button("chip", "问数命 SPU 社区 ↗", () => fill(document.querySelector(".starter[data-prompt*='带教'], .starter[data-prompt*='项目经验']").dataset.prompt)),
    button("chip", "问 SAIG 参赛 ↗", () => fill(document.querySelector(".starter[data-prompt*='线上赛']").dataset.prompt))
  );
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
  state.messages.push({role: "user", text: value});
  state.pending = {text: value, id: newId()};
  question.value = "";
  resizeInput();
  save();
  await sendPending();
}

async function sendPending() {
  if (busy || !state.pending) return;
  const pending = state.pending;
  busy = true;
  render();
  const start = performance.now();
  const progress = get("progress");
  progress.textContent = "正在整理答复…";
  const timer = setInterval(() => {
    progress.textContent = "正在整理答复… " + Math.floor((performance.now() - start) / 1000) + " 秒";
  }, 1000);
  try {
    const response = await fetch("/chat", {
      method: "POST", headers: apiHeaders(),
      body: JSON.stringify({query: pending.text, session: state.session, request_id: pending.id})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "暂时无法完成这次问答");
    state.session = result.session;
    state.messages.push({role: "assistant", result: {
      answer: result.answer, citations: result.citations, deliverables: result.deliverables
    }});
    updateBoard(result);
    animateReply = true;
    state.pending = null;
    setConnection("online");
    progress.textContent = "已回复 · " + ((performance.now() - start) / 1000).toFixed(1) + " 秒";
  } catch (error) {
    state.pending.error = error instanceof TypeError ? "连接中断，点击重试继续这条消息。" : error.message;
    progress.textContent = "等待重试";
    checkConnection();
  } finally {
    clearInterval(timer);
    busy = false;
    save();
    render();
    animateReply = false;
  }
}

get("composer").addEventListener("submit", event => {
  event.preventDefault();
  sendText(question.value);
});
question.addEventListener("input", resizeInput);
question.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendText(question.value);
  }
});
for (const starter of document.querySelectorAll(".starter")) {
  starter.addEventListener("click", () => sendText(starter.dataset.prompt));
}
get("start").addEventListener("click", () => {
  question.focus({preventScroll: true});
  question.scrollIntoView({block: "center"});
});
const exportButton = get("save-comparison");
exportButton.addEventListener("click", async () => {
  const result = currentComparison();
  if (!result) return;
  const rows = [].concat(...result.versions.map(version => {
    const stats = result.metrics?.[version.input];
    if (!stats) return [];
    const plan = state.plans.find(item => item.id === version.option_id);
    const arrivals = (stats.arrivals || []).map(arrival =>
      "第 " + arrival.day + " 天预计 " + routeTime.arrival(arrival.arrival, arrival.deadline) + " 到" + arrival.destination + "，最晚 " + routeTime.exact(arrival.deadline));
    const changedDay = plan?.replannedDays?.find(day =>
      Number.isInteger(plan.beforeCounts?.[day]) && plan.beforeCounts[day] !== stats.daily_stops[day - 1]);
    const change = changedDay ?
      "临时改口后，第 " + changedDay + " 天从 " + plan.beforeCounts[changedDay] + " 站改成 " + stats.daily_stops[changedDay - 1] + " 站" : "";
    return [{title: plan?.title || stats.days + " 天游览方案", stats, arrivals, change}];
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
    const response = await fetch("/session/delete", {method:"POST", headers:apiHeaders(),
      body: JSON.stringify({session: state.session})});
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
  get(id).addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "plans" : event.key === "End" ? "comparison" : activeTab === "plans" ? "comparison" : "plans";
    showTab(next, true);
  });
}
checkConnection();
render();
