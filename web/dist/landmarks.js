"use strict";
const Landmarks = /* @__PURE__ */ (() => {
  const S = 1.3, CX = 50, CY = 63;
  const P = (i, j, k = 0) => [CX + (i - j) * 0.866 * S, CY + (i + j) * 0.5 * S - k * S];
  const pts = (list) => list.map((p) => p.map((v) => v.toFixed(1)).join(",")).join(" ");
  const poly = (list, fill, extra = "") => '<polygon points="'.concat(pts(list), '" fill="').concat(fill, '" stroke="#4b3a2a" stroke-width=".5" stroke-linejoin="round"').concat(extra, "/>");
  function box(i0, j0, i1, j1, k0, k1, [top, left, right]) {
    return poly([P(i0, j1, k0), P(i1, j1, k0), P(i1, j1, k1), P(i0, j1, k1)], left) + poly([P(i1, j0, k0), P(i1, j1, k0), P(i1, j1, k1), P(i1, j0, k1)], right) + poly([P(i0, j0, k1), P(i1, j0, k1), P(i1, j1, k1), P(i0, j1, k1)], top);
  }
  function roof(i0, j0, i1, j1, k, h, o, [front, side], tips = true) {
    const a = [i0 - o, j0 - o], b = [i1 + o, j0 - o], c = [i1 + o, j1 + o], d = [i0 - o, j1 + o];
    const wi = i1 - i0, wj = j1 - j0, ic = (i0 + i1) / 2, jc = (j0 + j1) / 2;
    const [r1, r2] = wi >= wj ? [[i0 + wj / 2, jc], [i1 - wj / 2, jc]] : [[ic, j0 + wi / 2], [ic, j1 - wi / 2]];
    const R1 = P(r1[0], r1[1], k + h), R2 = P(r2[0], r2[1], k + h);
    let svg2 = wi >= wj ? poly([P(...b, k), P(...c, k), R2], side) + poly([P(...d, k), P(...c, k), R2, R1], front) : poly([P(...b, k), P(...c, k), R2, R1], side) + poly([P(...d, k), P(...c, k), R2], front);
    if (tips) for (const q of [d, c, b]) {
      const [x, y] = P(...q, k);
      svg2 += '<path d="M'.concat(x.toFixed(1), " ").concat(y.toFixed(1), "q").concat(q === d ? -2 : 2, " -.5 ").concat(q === d ? -2.6 : 2.6, ' -2.6" fill="none" stroke="#4b3a2a" stroke-width=".9" stroke-linecap="round"/>');
    }
    return svg2;
  }
  const tree = (i, j, r = 4, color = "#5f9e4b", k = 0) => {
    const [x, y] = P(i, j, k);
    return '<path d="M'.concat(x.toFixed(1), " ").concat(y.toFixed(1), "v-").concat((r * 0.9).toFixed(1), '" stroke="#6b4a2b" stroke-width="1.2"/>') + '<circle cx="'.concat(x.toFixed(1), '" cy="').concat((y - r * 1.3).toFixed(1), '" r="').concat(r, '" fill="').concat(color, '" stroke="#3e5f2e" stroke-width=".5"/>') + '<circle cx="'.concat((x - r * 0.35).toFixed(1), '" cy="').concat((y - r * 1.6).toFixed(1), '" r="').concat((r * 0.45).toFixed(1), '" fill="#ffffff" opacity=".18"/>');
  };
  const blossom = (i, j, r = 4.5) => tree(i, j, r, "#f6a9c4");
  const plate = (top = "#8fc46a", r = 24) => poly([P(-r, r, 0), P(r, r, 0), P(r, r, -5), P(-r, r, -5)], "#d39a55") + poly([P(r, -r, 0), P(r, r, 0), P(r, r, -5), P(r, -r, -5)], "#b97f3e") + poly([P(-r, r, 0), P(r, r, 0), P(r, r, -1.4), P(-r, r, -1.4)], "#7aa95a") + poly([P(r, -r, 0), P(r, r, 0), P(r, r, -1.4), P(r, -r, -1.4)], "#679347") + poly([P(-r, -r, 0), P(r, -r, 0), P(r, r, 0), P(-r, r, 0)], top);
  const water = (i0, j0, i1, j1) => poly([P(i0, j0), P(i1, j0), P(i1, j1), P(i0, j1)], "#5fb7c9", ' opacity=".95"') + '<path d="M'.concat(P(i0 + 4, j1 - 4)[0], " ").concat(P(i0 + 4, j1 - 4)[1], 'q3 -1.5 6 0t6 0" fill="none" stroke="#e8fbff" stroke-width=".8"/>');
  const svg = (body) => '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'.concat(body, "</svg>");
  const STONE = ["#f2e2c2", "#d9c19a", "#bfa47a"], RED = ["#e66a4e", "#c2452f", "#a03524"], CREAM = ["#fff4dc", "#ead6b0", "#d2b98c"];
  const GLASS = ["#bfe3f2", "#7fb8d6", "#5f97b8"], ROOF = ["#5f8f7a", "#477463"], GOLD = ["#f2b84b", "#d9952a"];
  const art = {
    customs: () => svg(plate() + box(-12, -8, 12, 10, 0, 16, STONE) + [-8, -3, 2, 7].map((i) => poly([P(i, 10, 2), P(i + 2.5, 10, 2), P(i + 2.5, 10, 13), P(i, 10, 13)], "#9c8462")).join("") + box(-4, -4, 4, 4, 16, 33, STONE) + roof(-4, -4, 4, 4, 33, 7, 1, ["#7c9c86", "#5e7f69"], false) + '<circle cx="'.concat(P(4, 0, 27)[0], '" cy="').concat(P(4, 0, 27)[1], '" r="2.8" fill="#fffaf0" stroke="#4b3a2a" stroke-width=".6"/>') + tree(-18, 14, 3.5) + tree(16, -16, 3.5)),
    lute: () => svg(plate() + box(-14, -14, 14, 14, 0, 3, STONE) + [[-8, 8], [8, 8], [8, -8], [-8, -8]].map(([i, j]) => box(i - 1, j - 1, i + 1, j + 1, 3, 15, RED)).join("") + roof(-9, -9, 9, 9, 15, 9, 3, ROOF) + tree(-18, -8, 4) + tree(14, -18, 3.5) + blossom(-16, 16, 3.5)),
    temple: () => svg(plate("#9ccc74") + box(-15, -9, 15, 9, 0, 3, STONE) + box(-12, -6, 12, 6, 3, 15, ["#f6d27a", "#e5b555", "#cf9a3c"]) + roof(-12, -6, 12, 6, 15, 5, 3, ["#a0522d", "#874320"]) + box(-8, -4, 8, 4, 19, 24, ["#f6d27a", "#e5b555", "#cf9a3c"]) + roof(-8, -4, 8, 4, 24, 6, 3, ["#a0522d", "#874320"]) + tree(-19, 15, 3.5) + tree(18, -17, 4, "#4f8d3f")),
    lake: () => svg(plate("#5fb7c9") + water(-24, -24, 24, 24) + box(-6, -6, 6, 6, 0, 3, STONE) + box(-4, -4, 4, 4, 3, 12, RED) + roof(-5, -5, 5, 5, 12, 5, 2.5, ROOF) + box(-3, -3, 3, 3, 15, 21, RED) + roof(-4, -4, 4, 4, 21, 5, 2.5, ROOF) + box(-2, -2, 2, 2, 24, 29, RED) + roof(-3, -3, 3, 3, 29, 6, 2, ROOF) + box(6, -2, 22, 2, 0, 1.5, STONE) + tree(-18, -16, 3.5) + blossom(17, -18, 3.5)),
    blossom: () => svg(plate() + poly([P(-20, 20), P(20, 20), P(16, -16, 0), P(-16, -16, 0)], "#8fc46a") + '<path d="M'.concat(P(-22, 18)[0], " ").concat(P(-22, 18)[1], "Q").concat(P(0, 0, 40)[0], " ").concat(P(0, 0, 40)[1], " ").concat(P(22, -18)[0], " ").concat(P(22, -18)[1], 'Z" fill="#7cb85a" stroke="#3e5f2e" stroke-width=".6"/>') + box(-2, -2, 2, 2, 20, 26, RED) + roof(-3, -3, 3, 3, 26, 5, 2, ROOF) + blossom(-14, 10, 5) + blossom(-4, 16, 5) + blossom(8, 10, 5) + blossom(14, -2, 4.5) + blossom(-16, -6, 4.5)),
    hust: () => svg(plate("#7fbf5c") + box(-12, -7, 12, 7, 0, 22, CREAM) + [-9, -4, 1, 6].map((i) => poly([P(i, 7, 4), P(i + 2.5, 7, 4), P(i + 2.5, 7, 19), P(i, 7, 19)], "#8fb0c4")).join("") + box(-14, -9, 14, 9, 22, 24, ["#e7e1d4", "#cfc6b4", "#b5ab96"]) + tree(-19, 13, 4.5, "#4f8d3f") + tree(-11, 18, 4, "#5f9e4b") + tree(15, 15, 4.5, "#4f8d3f") + tree(19, -12, 4, "#5f9e4b") + tree(4, 19, 3.5)),
    museum: () => svg(plate() + box(-16, -10, 16, 10, 0, 4, STONE) + box(-12, -7, 12, 7, 4, 16, CREAM) + roof(-12, -7, 12, 7, 16, 12, 5, ["#6f7d86", "#56626a"]) + box(-20, 13, -10, 15, 0, 13, ["#a56a3a", "#8a5530", "#6f4426"]) + [-18.5, -15, -11.5].map((i) => {
      const [x, y] = P(i, 15, 9);
      return '<path d="M'.concat(x.toFixed(1), " ").concat(y.toFixed(1), 'h3l.6 4.5h-4.2z" fill="').concat(GOLD[0], '" stroke="#4b3a2a" stroke-width=".5"/>');
    }).join("") + tree(18, -16, 4)),
    noodles: () => svg(plate("#d9c08f") + box(-14, -3, -11, 0, 0, 18, RED) + box(11, -3, 14, 0, 0, 18, RED) + box(-16, -4, 16, 1, 18, 21, RED) + roof(-17, -4, 17, 1, 21, 4, 2, ["#3d6b5a", "#2f5547"]) + '<ellipse cx="'.concat(P(4, 12)[0], '" cy="').concat(P(4, 12)[1] - 7, '" rx="11" ry="4.2" fill="#f6d27a" stroke="#4b3a2a" stroke-width=".6"/>') + '<path d="M'.concat(P(4, 12)[0] - 11, " ").concat(P(4, 12)[1] - 7, 'q11 14 22 0" fill="#ffffff" stroke="#4b3a2a" stroke-width=".6"/>') + '<path d="M'.concat(P(4, 12)[0] - 4, " ").concat(P(4, 12)[1] - 15, "q2 -3 0 -6M").concat(P(4, 12)[0] + 2, " ").concat(P(4, 12)[1] - 15, 'q2 -3 0 -6" fill="none" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/>')),
    lanterns: () => svg(plate("#d9c08f") + box(-16, -14, -4, 14, 0, 14, ["#f0d7b0", "#d6b88c", "#b99a6e"]) + roof(-16, -14, -4, 14, 14, 5, 1.5, ["#5b4a3f", "#45372e"], false) + box(4, -14, 16, 14, 0, 12, ["#f0d7b0", "#d6b88c", "#b99a6e"]) + roof(4, -14, 16, 14, 12, 5, 1.5, ["#5b4a3f", "#45372e"], false) + [-10, -2, 6].map((j) => {
      const [x, y] = P(-4, j, 9);
      return '<ellipse cx="'.concat(x.toFixed(1), '" cy="').concat(y.toFixed(1), '" rx="1.9" ry="2.4" fill="#e5412d" stroke="#7a1e14" stroke-width=".4"/>');
    }).join("") + [-6, 2, 10].map((j) => {
      const [x, y] = P(4, j, 8);
      return '<ellipse cx="'.concat(x.toFixed(1), '" cy="').concat(y.toFixed(1), '" rx="1.9" ry="2.4" fill="#e5412d" stroke="#7a1e14" stroke-width=".4"/>');
    }).join("")),
    redhouse: () => svg(plate() + box(-16, -7, 16, 7, 0, 15, RED) + [-12, -6, 0, 6, 11].map((i) => poly([P(i, 7, 4), P(i + 2, 7, 4), P(i + 2, 7, 11), P(i, 7, 11)], "#fff1d6")).join("") + box(-4, -4, 4, 4, 15, 24, RED) + '<path d="M'.concat(P(-4, 4, 24)[0], " ").concat(P(-4, 4, 24)[1], "Q").concat(P(0, 0, 36)[0], " ").concat(P(0, 0, 36)[1] - 4, " ").concat(P(4, -4, 24)[0], " ").concat(P(4, -4, 24)[1], 'Z" fill="#5b6f78" stroke="#4b3a2a" stroke-width=".5"/>') + '<path d="M'.concat(P(0, 0, 33)[0], " ").concat(P(0, 0, 33)[1], 'v-6" stroke="#4b3a2a" stroke-width=".7"/><path d="M').concat(P(0, 0, 33)[0], " ").concat(P(0, 0, 33)[1] - 6, 'h4l-1 1.4 1 1.4h-4" fill="#e5412d"/>') + tree(-20, 14, 3.5) + tree(19, -14, 3.5)),
    optics: () => svg(plate("#a6d0e0") + box(-18, -18, -8, -8, 0, 30, GLASS) + box(8, -20, 16, -12, 0, 24, GLASS) + box(-20, 8, -12, 16, 0, 22, GLASS) + '<ellipse cx="'.concat(P(4, 6, 14)[0], '" cy="').concat(P(4, 6, 14)[1], '" rx="13" ry="13" fill="none" stroke="#e8562d" stroke-width="2.6"/>') + '<ellipse cx="'.concat(P(4, 6, 14)[0], '" cy="').concat(P(4, 6, 14)[1], '" rx="13" ry="5" fill="none" stroke="#f2b84b" stroke-width="2"/>') + '<path d="M'.concat(P(4, 6)[0], " ").concat(P(4, 6)[1], 'v-8" stroke="#4b3a2a" stroke-width="1.4"/>')),
    tower: () => svg(plate("#a6d0e0") + box(-6, -6, 6, 6, 0, 36, GLASS) + box(-4, -4, 4, 4, 36, 42, ["#e8f6fb", "#a9d2e4", "#86b4cc"]) + '<path d="M'.concat(P(0, 0, 42)[0], " ").concat(P(0, 0, 42)[1], 'v-5" stroke="#4b3a2a" stroke-width=".8"/>') + box(10, -18, 18, -10, 0, 24, GLASS) + box(-20, 8, -12, 16, 0, 18, ["#f0e6d6", "#d4c6b0", "#b9a88e"]) + tree(14, 14, 3.5)),
    villa: () => svg(plate() + box(-12, -8, 12, 8, 0, 18, CREAM) + [-9, -4, 1, 6].map((i) => poly([P(i, 8, 9), P(i + 2.5, 8, 9), P(i + 2.5, 8, 15), P(i, 8, 15)], "#7fa6bd")).join("") + roof(-12, -8, 12, 8, 18, 9, 1.5, ["#d9663f", "#b84e2d"], false) + box(6, -3, 9, 0, 22, 30, ["#e8d8bc", "#cdb894", "#b19c77"]) + tree(-19, 14, 4) + tree(17, 14, 3.5) + tree(19, -14, 4, "#4f8d3f")),
    riverbank: () => svg(plate("#8fc46a") + water(-24, -24, 24, -2) + [0, 1, 2].map((n) => box(-24, -2 + n * 3, 24, 1 + n * 3, 0, 3 - n, ["#e9dcc0", "#cbb894", "#b19c77"])).join("") + box(-6, -18, 8, -12, 0, 4, ["#ffffff", "#e9eef2", "#cfd8de"]) + box(-3, -17, 4, -13, 4, 8, ["#ffffff", "#e9eef2", "#cfd8de"]) + '<path d="M'.concat(P(2, -15, 8)[0], " ").concat(P(2, -15, 8)[1], 'v-5" stroke="#e5412d" stroke-width="1.2"/>') + tree(-14, 16, 4) + tree(2, 18, 4) + tree(16, 14, 4, "#4f8d3f") + blossom(-20, 8, 3.5))
  };
  const LIST = [
    { name: "黄鹤楼", at: [30.54694, 114.29694], theme: "history", band: 0, size: 85, sprite: "tower" },
    { name: "木兰山", at: [31.103895, 114.389476], theme: "nature", band: 0, size: 86, sprite: "mountain" },
    { name: "东湖", at: [30.5651, 114.3689], theme: "nature", band: 0, size: 72, art: "lake" },
    { name: "光谷广场", at: [30.5083, 114.3929], theme: "modern", band: 0, size: 70, art: "optics" },
    { name: "武汉中心", at: [30.6065, 114.2624], theme: "modern", band: 0, size: 78, art: "tower" },
    { name: "武汉大学", at: [30.54083, 114.36111], theme: "campus", band: 1, size: 76, sprite: "campus" },
    { name: "华中科技大学", at: [30.51, 114.41], theme: "campus", band: 1, size: 62, art: "hust" },
    { name: "湖北省博物馆", at: [30.5639, 114.3589], theme: "history", band: 1, size: 64, art: "museum" },
    { name: "磨山樱花园", at: [30.556, 114.413], theme: "nature", band: 1, size: 64, art: "blossom" },
    { name: "归元寺", at: [30.5496, 114.2575], theme: "history", band: 1, size: 60, art: "temple" },
    { name: "江汉关", at: [30.5787, 114.2921], theme: "river", band: 1, size: 62, art: "customs" },
    { name: "武汉长江大桥", at: [30.5518, 114.2835], theme: "river", band: 2, size: 84, sprite: "bridge" },
    { name: "汉口江滩", at: [30.5839, 114.2956], theme: "river", band: 2, size: 60, art: "riverbank" },
    { name: "古琴台", at: [30.5567, 114.2583], theme: "history", band: 2, size: 56, art: "lute" },
    { name: "户部巷", at: [30.5498, 114.2926], theme: "food", band: 2, size: 54, art: "noodles" },
    { name: "吉庆街", at: [30.588, 114.2861], theme: "food", band: 2, size: 54, art: "lanterns" },
    { name: "辛亥革命武昌起义纪念馆", at: [30.5432, 114.3035], theme: "red", band: 2, size: 58, art: "redhouse" },
    { name: "黎黄陂路", at: [30.5893, 114.2952], theme: "history", band: 2, size: 54, art: "villa" }
  ];
  const THEMES = { all: "全部", history: "历史", river: "江景", nature: "自然", campus: "高校", food: "美食", modern: "现代", red: "红色" };
  const cache = {};
  const html = (item) => {
    var _a;
    return item.art ? cache[_a = item.art] || (cache[_a] = art[item.art]()) : "";
  };
  return { LIST, THEMES, html };
})();
