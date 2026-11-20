// 3D flyover of a Wuhan itinerary: a diorama of the city (the street map as a raised tile), the
// painted landmarks standing on it, the route drawn as it is flown, the porpoise guide swimming
// along it, and "climb and look out" views at the high points. Loaded on demand (bundled with three).
import * as THREE from "three";
import {OrbitControls} from "three/examples/jsm/controls/OrbitControls.js";

const TILE = {x0: 3346, x1: 3351, y0: 1680, y1: 1684};
const W = 50, H = 40;                       // ground size in scene units (texture is 2560 x 2048 tile px)
const VIEWS = {
  "黄鹤楼": {img: "view-hhl", title: "登黄鹤楼 · 望龟蛇锁大江"},
  "龟山公园": {img: "view-guishan", title: "登龟山 · 隔江望黄鹤楼"},
  "武汉长江大桥": {img: "view-bridge", title: "走上长江大桥 · 万里长江第一桥"},
  "东湖听涛": {img: "view-moshan", title: "登磨山 · 俯瞰东湖"},
  "东湖风景区": {img: "view-moshan", title: "登磨山 · 俯瞰东湖"},
  "东湖绿道": {img: "view-moshan", title: "登磨山 · 俯瞰东湖"}
};
const SPRITES = {tower: "lm-sprite-tower", bridge: "lm-sprite-bridge", campus: "lm-sprite-campus", mountain: "lm-sprite-mountain"};

function tile(lat, lon) {
  const x = (lon + 180) / 360 * 4096;
  const r = lat * Math.PI / 180;
  const y = (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * 4096;
  return [(x - TILE.x0) / (TILE.x1 - TILE.x0), (y - TILE.y0) / (TILE.y1 - TILE.y0)];
}
function toScene(lat, lon, h = 0) {
  const [u, v] = tile(lat, lon);
  return new THREE.Vector3((u - .5) * W, h, (v - .5) * H);
}
const inside = (lat, lon) => { const [u, v] = tile(lat, lon); return u > -.02 && u < 1.02 && v > -.02 && v < 1.02; };
const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
const sleep = ms => new Promise(r => setTimeout(r, ms));

function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }

function badge(n, color = "#1b46b9") {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = color; g.beginPath(); g.arc(64, 64, 52, 0, Math.PI * 2); g.fill();
  g.lineWidth = 10; g.strokeStyle = "#fff"; g.stroke();
  g.fillStyle = "#fff"; g.font = "bold 62px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(String(n), 64, 68);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
function cloudTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(64, 64, 6, 64, 64, 62);
  grad.addColorStop(0, "rgba(255,255,255,.95)"); grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

function open({stops, title = "3D 飞览", landmarks = [], say = null, onClose = null}) {
  if (document.getElementById("flyover")) return;
  const probe = document.createElement("canvas");
  if (!(probe.getContext("webgl2") || probe.getContext("webgl"))) { alert("这台设备的浏览器不支持 3D 显示。"); return; }

  const root = el("div", "flyover"); root.id = "flyover"; root.setAttribute("role", "dialog"); root.setAttribute("aria-label", title);
  const stage = el("div", "flyover-stage");
  const head = el("div", "flyover-head");
  head.append(el("strong", "", title), el("span", "flyover-hint", "拖动可旋转 · 滚轮缩放"));
  const caption = el("div", "flyover-caption"); caption.hidden = true;
  const view = el("figure", "flyover-view"); view.hidden = true;
  const viewImg = el("img"); viewImg.alt = "";
  const viewCap = el("figcaption");
  view.append(viewImg, viewCap);
  const bar = el("div", "flyover-bar");
  const pauseBtn = el("button", "", "暂停"), skipBtn = el("button", "", "下一站"), replayBtn = el("button", "", "重播"), closeBtn = el("button", "flyover-close", "关闭");
  for (const b of [pauseBtn, skipBtn, replayBtn, closeBtn]) b.type = "button";
  bar.append(pauseBtn, skipBtn, replayBtn, closeBtn);
  const progress = el("ol", "flyover-steps");
  root.append(stage, head, caption, view, progress, bar);
  document.body.append(root);
  document.body.classList.add("flyover-open");

  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  stage.append(renderer.domElement);
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xcfe6f1, 46, 110);
  const camera = new THREE.PerspectiveCamera(38, 1, .1, 400);
  camera.position.set(0, 42, 34);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.maxPolarAngle = Math.PI * .45; controls.minDistance = 4; controls.maxDistance = 80;
  controls.enabled = false;
  const loader = new THREE.TextureLoader();
  const tex = url => { const t = loader.load(url); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = renderer.capabilities.getMaxAnisotropy(); return t; };

  // Diorama: the street map on a raised earth tile.
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(W, H), new THREE.MeshBasicMaterial({map: tex("/web/atlas/ground-3d.webp")}));
  ground.rotation.x = -Math.PI / 2; scene.add(ground);
  const sides = new THREE.Mesh(new THREE.BoxGeometry(W, 1.6, H), [
    new THREE.MeshBasicMaterial({color: 0xc98a45}), new THREE.MeshBasicMaterial({color: 0xc98a45}),
    new THREE.MeshBasicMaterial({color: 0x000000, transparent: true, opacity: 0}), new THREE.MeshBasicMaterial({color: 0x8a5a2b}),
    new THREE.MeshBasicMaterial({color: 0xdba15e}), new THREE.MeshBasicMaterial({color: 0xb57a3c})]);
  sides.position.y = -.81; scene.add(sides);
  const grass = new THREE.Mesh(new THREE.BoxGeometry(W + .02, .25, H + .02), new THREE.MeshBasicMaterial({color: 0x8fbf5f}));
  grass.position.y = -.13; scene.add(grass);

  // Landmarks.
  for (const item of landmarks) {
    const [lat, lon] = item.at;
    if (!inside(lat, lon)) continue;
    const file = item.sprite ? SPRITES[item.sprite] : "lm-" + item.art;
    const s = new THREE.Sprite(new THREE.SpriteMaterial({map: tex(`/web/atlas/${file}.webp`), transparent: true, depthWrite: false}));
    s.center.set(.5, .08);
    const size = 1.1 + (item.size || 70) / 85;
    s.scale.set(size, size, 1);
    s.position.copy(toScene(lat, lon, .02));
    s.renderOrder = 2;
    scene.add(s);
  }
  // Drifting clouds.
  const cloudTex = cloudTexture(), clouds = [];
  for (let i = 0; i < 9; i++) {
    const c = new THREE.Sprite(new THREE.SpriteMaterial({map: cloudTex, transparent: true, opacity: .55, depthWrite: false, fog: false}));
    const s = 6 + Math.random() * 6; c.scale.set(s * 1.8, s, 1);
    c.position.set((Math.random() - .5) * W * 1.2, 9 + Math.random() * 5, (Math.random() - .5) * H * 1.2);
    c.userData.speed = .15 + Math.random() * .25; scene.add(c); clouds.push(c);
  }

  // Route.
  const pts = stops.map(s => toScene(s.lat, s.lon, .25));
  const path = [];
  for (let i = 0; i < pts.length; i++) {
    path.push(pts[i]);
    if (i < pts.length - 1) {
      const mid = pts[i].clone().lerp(pts[i + 1], .5);
      mid.y += .4 + pts[i].distanceTo(pts[i + 1]) * .12;
      path.push(mid);
    }
  }
  const curve = new THREE.CatmullRomCurve3(path, false, "centripetal");
  const segs = Math.max(60, stops.length * 60);
  const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, segs, .09, 8, false), new THREE.MeshBasicMaterial({color: 0xe8562d}));
  tube.geometry.setDrawRange(0, 0); tube.renderOrder = 3; scene.add(tube);
  const total = tube.geometry.index.count;
  // Arc-length position of each stop on the curve.
  const at = pts.map(p => { let best = 0, d = Infinity; for (let i = 0; i <= 400; i++) { const q = curve.getPointAt(i / 400); const e = q.distanceTo(p); if (e < d) { d = e; best = i / 400; } } return best; });
  const markers = stops.map((s, i) => {
    const m = new THREE.Sprite(new THREE.SpriteMaterial({map: badge(s.label || i + 1, s.kind === "end" ? "#e8562d" : "#1b46b9"), depthTest: false, transparent: true}));
    m.scale.set(.75, .75, 1); m.position.copy(pts[i]).add(new THREE.Vector3(0, 1.9, 0)); m.renderOrder = 5; m.visible = false; scene.add(m);
    return m;
  });
  const guide = new THREE.Sprite(new THREE.SpriteMaterial({map: tex("/web/porpoise.webp"), transparent: true, depthTest: false}));
  guide.scale.set(1.15, 1.15, 1); guide.center.set(.5, .2); guide.renderOrder = 6; guide.position.copy(pts[0]); scene.add(guide);

  // Steps strip.
  stops.forEach((s, i) => { const li = el("li", "", s.name); li.dataset.i = i; progress.append(li); });
  const mark = i => progress.querySelectorAll("li").forEach((li, k) => li.className = k < i ? "done" : k === i ? "now" : "");

  // Loop.
  let alive = true, guideT = 0, routeT = 0;
  const clock = new THREE.Clock();
  function resize() { const w = stage.clientWidth, h = stage.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
  window.addEventListener("resize", resize); resize();
  const lookAt = new THREE.Vector3(0, 0, 0);
  function frame() {
    if (!alive) return;
    const dt = clock.getDelta(), t = clock.elapsedTime;
    for (const c of clouds) { c.position.x += c.userData.speed * dt; if (c.position.x > W) c.position.x = -W; }
    tube.geometry.setDrawRange(0, Math.floor(total * routeT / 3) * 3);
    const p = curve.getPointAt(Math.min(1, Math.max(0, guideT)));
    guide.position.set(p.x + .55, p.y + .1 + Math.sin(t * 3) * .08, p.z + .35);
    if (controls.enabled) controls.update(); else camera.lookAt(lookAt);
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // Camera choreography.
  let paused = false, skip = false, run = 0;
  const wait = async ms => { const end = performance.now() + ms; while (performance.now() < end) { if (!alive || skip) return; await sleep(paused ? 120 : 30); } };
  async function fly(toPos, toLook, ms, from = {}) {
    const p0 = camera.position.clone(), l0 = lookAt.clone();
    const r0 = routeT, g0 = guideT, start = performance.now();
    let elapsed = 0, last = start;
    while (elapsed < ms && alive && !skip) {
      const now = performance.now(); if (!paused) elapsed += now - last; last = now;
      const k = ease(Math.min(1, elapsed / ms));
      camera.position.lerpVectors(p0, toPos, k); lookAt.lerpVectors(l0, toLook, k);
      if (from.route != null) routeT = r0 + (from.route - r0) * k;
      if (from.guide != null) guideT = g0 + (from.guide - g0) * k;
      await sleep(16);
    }
    camera.position.copy(toPos); lookAt.copy(toLook);
    if (from.route != null) routeT = from.route;
    if (from.guide != null) guideT = from.guide;
  }
  function overview() {
    const box = new THREE.Box3().setFromPoints(pts.length ? pts : [new THREE.Vector3()]);
    const c = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()).length();
    return {pos: c.clone().add(new THREE.Vector3(0, 10 + size * .9, 8 + size * .75)), look: c};
  }
  async function lookout(stop) {
    const v = VIEWS[stop.name]; if (!v) return;
    const up = camera.position.clone().add(new THREE.Vector3(0, 5, 0));
    await fly(up, lookAt.clone().add(new THREE.Vector3(0, 1.5, 0)), 1100);
    viewImg.src = `/web/atlas/${v.img}.webp`;
    viewCap.textContent = v.title + " · AI 绘制示意";
    view.hidden = false; view.classList.remove("show"); void view.offsetWidth; view.classList.add("show");
    await wait(5200);
    view.classList.remove("show"); await sleep(450); view.hidden = true;
  }
  async function play() {
    const id = ++run;
    controls.enabled = false; caption.hidden = true; routeT = 0; guideT = 0;
    markers.forEach(m => m.visible = false);
    const o = overview();
    camera.position.copy(o.pos.clone().add(new THREE.Vector3(0, 14, 10))); lookAt.copy(o.look);
    await fly(o.pos, o.look, 2200);
    for (let i = 0; i < stops.length && alive && id === run; i++) {
      skip = false;
      const s = stops[i], target = pts[i];
      const angle = -.6 + i * .55, dist = 8.5;
      const pos = target.clone().add(new THREE.Vector3(Math.sin(angle) * dist, 6.2, Math.cos(angle) * dist));
      mark(i);
      await fly(pos, target.clone().add(new THREE.Vector3(0, .6, 0)), i === 0 ? 2000 : 2600, {route: at[i], guide: at[i]});
      if (id !== run) return;
      markers[i].visible = true;
      caption.replaceChildren(el("small", "", s.kicker || `第 ${i + 1} 站`), el("strong", "", s.name), el("span", "", s.detail || ""));
      caption.hidden = false;
      if (say && s.say) say(s.say);
      await wait(2300);
      if (!skip) await lookout(s);
      caption.hidden = true;
    }
    if (id !== run || !alive) return;
    skip = false; routeT = 1; markers.forEach(m => m.visible = true); mark(stops.length);
    const end = overview();
    await fly(end.pos, end.look, 2400);
    caption.replaceChildren(el("small", "", "全程"), el("strong", "", `${stops.length} 站`), el("span", "", "拖动可以转着看 · 路线已在行程板，可导出到高德"));
    caption.hidden = false;
    controls.target.copy(end.look); controls.enabled = true;
    pauseBtn.disabled = skipBtn.disabled = true;
  }
  pauseBtn.onclick = () => { paused = !paused; pauseBtn.textContent = paused ? "继续" : "暂停"; };
  skipBtn.onclick = () => { skip = true; };
  replayBtn.onclick = () => { paused = false; pauseBtn.textContent = "暂停"; pauseBtn.disabled = skipBtn.disabled = false; skip = true; setTimeout(play, 60); };
  function close() {
    alive = false; window.removeEventListener("resize", resize); document.removeEventListener("keydown", onKey);
    renderer.dispose(); root.remove(); document.body.classList.remove("flyover-open"); onClose && onClose();
  }
  const onKey = e => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  closeBtn.onclick = close;
  closeBtn.focus();
  play();
  return {close};
}

window.Flyover = {open};
