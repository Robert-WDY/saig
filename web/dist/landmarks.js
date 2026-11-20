"use strict";
const Landmarks = /* @__PURE__ */ (() => {
  const LIST = [
    { name: "黄鹤楼", at: [30.54694, 114.29694], theme: "history", band: 0, size: 85, sprite: "tower" },
    { name: "木兰山", at: [31.103895, 114.389476], theme: "nature", band: 0, size: 86, sprite: "mountain" },
    { name: "东湖", at: [30.5651, 114.3689], theme: "nature", band: 0, size: 86, art: "lake" },
    { name: "光谷广场", at: [30.5083, 114.3929], theme: "modern", band: 0, size: 84, art: "optics" },
    { name: "武汉中心", at: [30.6065, 114.2624], theme: "modern", band: 0, size: 92, art: "tower" },
    { name: "武汉大学", at: [30.54083, 114.36111], theme: "campus", band: 1, size: 76, sprite: "campus" },
    { name: "华中科技大学", at: [30.51, 114.41], theme: "campus", band: 1, size: 76, art: "hust" },
    { name: "湖北省博物馆", at: [30.5639, 114.3589], theme: "history", band: 1, size: 78, art: "museum" },
    { name: "磨山樱花园", at: [30.556, 114.413], theme: "nature", band: 1, size: 78, art: "blossom" },
    { name: "归元寺", at: [30.5496, 114.2575], theme: "history", band: 1, size: 74, art: "temple" },
    { name: "江汉关", at: [30.5787, 114.2921], theme: "river", band: 1, size: 76, art: "customs" },
    { name: "武汉长江大桥", at: [30.5518, 114.2835], theme: "river", band: 2, size: 84, sprite: "bridge" },
    { name: "汉口江滩", at: [30.5839, 114.2956], theme: "river", band: 2, size: 74, art: "riverbank" },
    { name: "古琴台", at: [30.5567, 114.2583], theme: "history", band: 2, size: 70, art: "lute" },
    { name: "户部巷", at: [30.5498, 114.2926], theme: "food", band: 2, size: 68, art: "noodles" },
    { name: "吉庆街", at: [30.588, 114.2861], theme: "food", band: 2, size: 68, art: "lanterns" },
    { name: "辛亥革命武昌起义纪念馆", at: [30.5432, 114.3035], theme: "red", band: 2, size: 72, art: "redhouse" },
    { name: "黎黄陂路", at: [30.5893, 114.2952], theme: "history", band: 2, size: 68, art: "villa" }
  ];
  const THEMES = { all: "全部", history: "历史", river: "江景", nature: "自然", campus: "高校", food: "美食", modern: "现代", red: "红色" };
  const html = (item) => item.art ? '<img src="/web/atlas/lm-'.concat(item.art, '.webp" alt="" loading="lazy" decoding="async">') : "";
  return { LIST, THEMES, html };
})();
