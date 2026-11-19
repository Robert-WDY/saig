"use strict";

// The official SAIG porpoise is the receptionist: it blinks while idle, nods while
// the backend is working and talks (optionally aloud through the browser voice) when a reply arrives.
const Receptionist = (() => {
  const voiceKey = "saig-receptionist-voice";
  const synth = "speechSynthesis" in window ? window.speechSynthesis : null;
  const status = {
    idle: "在线 · 武汉、社区、行程、SAIG 都能问",
    thinking: "正在查资料、排路线…",
    speaking: "正在为你讲解",
    happy: "好啦，看看合不合心意？",
    error: "线路有点忙，可以再试一次"
  };
  let state = "idle", talkTimer = 0, settleTimer = 0, voiceOn = readVoice(), chosenVoice = null;

  function readVoice() {
    try { return localStorage.getItem(voiceKey) !== "off"; } catch { return true; }
  }
  function storeVoice() {
    try { localStorage.setItem(voiceKey, voiceOn ? "on" : "off"); } catch {}
  }
  function build(host) {
    if (host.querySelector(".porpoise")) return;
    const figure = document.createElement("div");
    figure.className = "porpoise";
    figure.setAttribute("aria-hidden", "true");
    figure.innerHTML = '<span class="porpoise-waves"><i></i><i></i></span>' +
      '<div class="porpoise-body"><img src="/web/porpoise.webp" alt="" width="360" height="356" decoding="async">' +
      '<i class="lid l"></i><i class="lid r"></i><i class="blush l"></i><i class="blush r"></i></div>' +
      '<span class="porpoise-shadow"></span><span class="porpoise-dots"><i></i><i></i><i></i></span>';
    host.append(figure);
  }
  function hosts() { return document.querySelectorAll("[data-porpoise]"); }
  function apply() {
    for (const host of hosts()) { build(host); host.dataset.state = state; }
    for (const line of document.querySelectorAll("[data-porpoise-status]")) line.textContent = status[state] || status.idle;
  }
  function set(next) {
    clearTimeout(settleTimer);
    state = next;
    apply();
    if (next === "happy" || next === "error") settleTimer = setTimeout(() => set("idle"), 4200);
  }
  function blink() {
    for (const host of hosts()) {
      host.classList.add("blink");
      setTimeout(() => host.classList.remove("blink"), 170);
    }
    setTimeout(blink, 2600 + Math.random() * 3200);
  }
  function beat() {
    for (const host of hosts()) {
      const body = host.querySelector(".porpoise-body");
      if (!body) continue;
      body.classList.remove("beat");
      void body.offsetWidth;
      body.classList.add("beat");
    }
  }
  function pickVoice() {
    if (!synth) return null;
    const voices = synth.getVoices().filter(v => /^zh(-|_)?(CN|Hans)?/i.test(v.lang) && !/HK|TW/i.test(v.lang));
    const liked = ["Xiaoxiao", "Xiaoyi", "晓晓", "晓伊", "Tingting", "婷婷", "Huihui", "慧慧", "Google 普通话"];
    return liked.map(name => voices.find(v => v.name.includes(name))).find(Boolean) || voices[0] || null;
  }
  if (synth) synth.addEventListener?.("voiceschanged", () => { chosenVoice = pickVoice(); });

  function clean(text) {
    return String(text || "")
      .replace(/https?:\/\/\S+/g, "")
      .replace(/[（(][^）)]{0,40}[)）]/g, "")
      .replace(/\b(\d{1,2}):(\d{2})/g, (_, h, m) => Number(h) + "点" + (m === "00" ? "" : m === "30" ? "半" : Number(m) + "分"))
      .replace(/[→]/g, "，").replace(/[·•]/g, "，").replace(/\s+/g, " ").trim();
  }
  // Pretend to talk for a time proportional to the text when the voice is off or unavailable.
  function mime(text) {
    clearInterval(talkTimer);
    set("speaking");
    const end = performance.now() + Math.min(5200, Math.max(1400, text.length * 55));
    talkTimer = setInterval(() => {
      if (performance.now() > end) { clearInterval(talkTimer); set("happy"); return; }
      beat();
    }, 230);
  }
  function say(text) {
    const spoken = clean(text).slice(0, 260);
    stop();
    if (!spoken) { set("happy"); return; }
    if (!voiceOn || !synth) { mime(spoken); return; }
    const utterance = new SpeechSynthesisUtterance(spoken);
    utterance.lang = "zh-CN";
    utterance.rate = 1.08;
    utterance.pitch = 1.18;
    chosenVoice = chosenVoice || pickVoice();
    if (chosenVoice) utterance.voice = chosenVoice;
    let boundaries = false;
    utterance.onstart = () => {
      set("speaking");
      // Some voices never fire boundary events; keep the mouth moving anyway.
      talkTimer = setInterval(() => { if (!boundaries) beat(); }, 240);
    };
    utterance.onboundary = () => { boundaries = true; beat(); };
    utterance.onend = utterance.onerror = () => { clearInterval(talkTimer); if (state === "speaking") set("happy"); };
    synth.speak(utterance);
    // Browsers that block speech never fire onstart.
    setTimeout(() => { if (state !== "speaking" && !synth.speaking) mime(spoken); }, 900);
  }
  function stop() {
    clearInterval(talkTimer);
    if (synth && (synth.speaking || synth.pending)) synth.cancel();
  }
  function syncToggle() {
    for (const toggle of document.querySelectorAll("[data-voice-toggle]")) {
      toggle.setAttribute("aria-pressed", String(voiceOn));
      toggle.innerHTML = '<svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true"><path d="M3 7.5h3l4-3.5v12l-4-3.5H3z" fill="currentColor"/>' +
        (voiceOn ? '<path d="M13 7a4 4 0 0 1 0 6M15.5 4.5a7.5 7.5 0 0 1 0 11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
                 : '<path d="M13.5 8l4 4m0-4l-4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>') +
        '</svg>' + (voiceOn ? "语音播报" : "语音已关");
      toggle.hidden = !synth;
    }
  }
  function toggleVoice() {
    voiceOn = !voiceOn;
    storeVoice();
    if (!voiceOn) stop();
    syncToggle();
  }
  function init() {
    apply();
    syncToggle();
    for (const toggle of document.querySelectorAll("[data-voice-toggle]")) toggle.addEventListener("click", toggleVoice);
    setTimeout(blink, 1800);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
  return {set, say, stop, get state() { return state; }};
})();
