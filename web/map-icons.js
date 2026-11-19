"use strict";

// Screen-print map icons in the site palette: ink-blue strokes, orange and sand fills.
// One icon per place, chosen by name first and by category/topic as a fallback.
const MapIcons = (() => {
  const O = 'fill="#e8562d"', S = 'fill="#ffdfbc"', N = 'fill="none"';
  const shapes = {
    pagoda: `<path d="M12 2.5v3"/><path ${O} d="M6.5 8h11l-2-2.6h-7z"/><path ${O} d="M5 13h14l-2.2-2.7H7.2z"/><path ${O} d="M3.8 18.4h16.4l-2.3-2.8H6.1z"/><path d="M8.6 8v2.3M15.4 8v2.3M7.8 13v2.6M16.2 13v2.6M5 21.4h14"/>`,
    bridge: `<path ${O} d="M5 4.5h2.6V10H5zM16.4 4.5H19V10h-2.6z"/><path d="M2 10h20M2 12.6h20"/><path ${N} d="M3 21v-5.6a2.3 2.3 0 0 1 4.6 0V21M9.7 21v-5.6a2.3 2.3 0 0 1 4.6 0V21M16.4 21v-5.6a2.3 2.3 0 0 1 4.6 0V21"/>`,
    museum: `<path ${O} d="M3 9.2 12 4l9 5.2z"/><path d="M6 10.5v7.5M10 10.5v7.5M14 10.5v7.5M18 10.5v7.5M3.6 19h16.8M2.6 21.4h18.8"/>`,
    bells: `<path d="M2.5 4h19M5.8 4v2.4M12 4v2.4M18.2 4v2.4"/><path ${O} d="M4 6.6h3.6l1.1 8.6H2.9zM10.2 6.6h3.6l1.3 10.8H8.9zM16.4 6.6H20l1.1 8.6h-5.8z"/><path d="M3 21.4h18"/>`,
    clock: `<path ${O} d="M8.6 21V9.2h6.8V21z"/><path d="M8.1 9.2 12 4.8l3.9 4.4M12 4.8V2.5M5 21.4h14M5.2 21v-5.8h3.4M15.4 15.2h3.4V21"/><circle cx="12" cy="12.6" r="2" fill="#fffaf0"/><path d="M12 11.6v1.1l.8.6"/>`,
    lake: `<path ${O} d="M8 9h8l-1.6-2.6H9.6z"/><path d="M9.4 9v2.6M14.6 9v2.6"/><path ${N} d="M2.5 15c1.6-1.6 3.2-1.6 4.8 0s3.2 1.6 4.8 0 3.2-1.6 4.8 0 3.2 1.6 4.6 0M2.5 19.4c1.6-1.6 3.2-1.6 4.8 0s3.2 1.6 4.8 0 3.2-1.6 4.8 0 3.2 1.6 4.6 0"/>`,
    tree: `<circle cx="9" cy="9.5" r="5" ${O}/><circle cx="16.4" cy="12" r="3.7" ${S}/><path d="M9 14.5v6.9M16.4 15.7v5.7M3.5 21.4h17"/>`,
    mountain: `<circle cx="17.5" cy="5.5" r="2.2" ${S}/><path ${O} d="m2 20.5 6.2-10.8 4.2 5.4 3-4 6.6 9.4z"/><path d="M6.4 13 8.2 9.7l1.6 2.1"/>`,
    noodles: `<path d="m14.2 2.8 3.6 8M17.4 2.6l2.2 8.6"/><path ${O} d="M3.4 11.6h17.2a8.6 6.8 0 0 1-17.2 0z"/><path ${N} d="M6.6 11.6c.9-1.4 1.8 1.4 2.7 0s1.8 1.4 2.7 0 1.8 1.4 2.7 0 1.8 1.4 2.7 0"/><path d="M8.8 20.8h6.4"/>`,
    lantern: `<path d="M12 2.4v2.4M9 4.8h6"/><ellipse cx="12" cy="10.8" rx="5.2" ry="5.6" ${O}/><path d="M12 5.4v10.8M8.2 7.2c-1.4 2.4-1.4 5 0 7.2M15.8 7.2c1.4 2.4 1.4 5 0 7.2M9 16.6h6M12 16.6v3.2M10.8 21.4l1.2-1.6 1.2 1.6"/>`,
    campus: `<path ${O} d="M2 9.4 12 4.8l10 4.6-10 4.6z"/><path ${N} d="M6 11.4v4.4c0 1.6 2.8 3 6 3s6-1.4 6-3v-4.4M21 9.6v5.4"/>`,
    boat: `<path ${O} d="M2.4 14.8h19.2l-2.6 5H5z"/><path d="M6 14.8v-4h9.6v4M12.6 10.8V7h2.6v3.8M8.4 12.6h1.4"/>`,
    flag: `<path d="M5.8 21.6V2.6M3.4 21.6h5"/><path ${O} d="M5.8 3.6h12.4L15.6 7.4l2.6 3.8H5.8z"/>`,
    shopping: `<path ${O} d="M5 8.2h14l-1 13.2H6z"/><path ${N} d="M9 8.2V6.4a3 3 0 0 1 6 0v1.8"/><path d="M9 12.4a3 3 0 0 0 6 0"/>`,
    monorail: `<path d="M2 5.4h20M8 5.4v2.4M16 5.4v2.4"/><rect x="4" y="7.8" width="16" height="8.6" rx="2.4" ${O}/><path d="M7.2 10.6h3.4v2.6H7.2zM13.4 10.6h3.4v2.6h-3.4z" fill="#fffaf0"/><path d="M7 19.2h10"/>`,
    factory: `<path ${O} d="M3 21.4v-9l5 3v-3l5 3v-3l5 3V5.2h3v16.2z"/><path ${N} d="M18.6 3.6c.6-.8 1.6-.8 2.2 0"/>`,
    flower: `<circle cx="12" cy="6.6" r="3" ${O}/><circle cx="7.4" cy="10.2" r="3" ${O}/><circle cx="16.6" cy="10.2" r="3" ${O}/><circle cx="9.2" cy="14.6" r="3" ${O}/><circle cx="14.8" cy="14.6" r="3" ${O}/><circle cx="12" cy="11.2" r="2" fill="#fffaf0"/><path d="M12 17.6v4"/>`,
    wheel: `<circle cx="12" cy="9.4" r="6.6" ${N}/><circle cx="12" cy="9.4" r="1.4" ${O}/><path d="M12 2.8v13.2M5.4 9.4h13.2M7.3 4.7l9.4 9.4M16.7 4.7l-9.4 9.4M12 9.4l-4.2 12M12 9.4l4.2 12M6.4 21.4h11.2"/><circle cx="12" cy="2.8" r="1.2" ${O}/><circle cx="18.6" cy="9.4" r="1.2" ${O}/><circle cx="5.4" cy="9.4" r="1.2" ${O}/>`,
    paw: `<ellipse cx="12" cy="15.6" rx="4.6" ry="4" ${O}/><circle cx="6" cy="10" r="2" ${O}/><circle cx="9.6" cy="6.4" r="2" ${O}/><circle cx="14.4" cy="6.4" r="2" ${O}/><circle cx="18" cy="10" r="2" ${O}/>`,
    gate: `<path ${O} d="M3 7.4h18l-1.6-2.6H4.6z"/><path d="M5 7.4v14M19 7.4v14M9.4 7.4v14M14.6 7.4v14M3.6 11h16.8M3 21.4h18"/>`,
    pin: `<path ${O} d="M12 21.6s-6.4-6.2-6.4-11a6.4 6.4 0 0 1 12.8 0c0 4.8-6.4 11-6.4 11z"/><circle cx="12" cy="10.4" r="2.4" fill="#fffaf0"/>`
  };
  const names = [
    [/黄鹤楼|晴川阁|古琴台|阁$|塔/, "pagoda"], [/大桥/, "bridge"], [/湖北省博物馆/, "bells"], [/江汉关/, "clock"],
    [/革命|八七|中共|首义|辛亥|中山舰|旧址/, "flag"], [/知音号|游船|码头/, "boat"], [/空轨/, "monorail"],
    [/汉阳造|武钢|工业|红糖|周黑鸭/, "factory"], [/天地|汉街|广场|商圈/, "shopping"], [/动物/, "paw"],
    [/欢乐谷|乐园|海洋|趣谷|牧场|有田|问津|稻田/, "wheel"], [/湖|江滩|湿地|海/, "lake"],
    [/山|寨|谷|岭/, "mountain"], [/花|茶|田园|莲|桃源|蝴蝶/, "flower"], [/巷|街|里$|路$|城$|镇|湾|营/, "lantern"]
  ];
  const topics = {"展馆文博": "museum", "公园山水": "tree", "亲子游乐": "wheel", "地方美食": "noodles", "高校校园": "campus", "城市人文": "gate"};
  function kind(row) {
    if (row.category === "大学") return "campus";
    if (row.category === "美食") return "noodles";
    // "中山" is a person's name (Sun Yat-sen), not a hill.
    const name = (row.name || "").replace(/中山/g, "");
    const hit = names.find(([pattern]) => pattern.test(name));
    return hit ? hit[1] : topics[row.topic] || "pin";
  }
  function svg(name, size = 22) {
    return '<svg viewBox="0 0 24 24" width="' + size + '" height="' + size + '" aria-hidden="true" fill="none" stroke="#12399d" ' +
      'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' + (shapes[name] || shapes.pin) + "</svg>";
  }
  return {kind, svg, for: (row, size) => svg(kind(row), size), names: Object.keys(shapes)};
})();
