"use strict";

async function downloadComparisonPoster(rows) {
  const art = document.querySelector(".hero img");
  if (art.decode) await art.decode();
  const canvas = document.createElement("canvas");
  canvas.width = 1080;
  canvas.height = 925 + rows.length * 215;
  const ctx = canvas.getContext("2d");
  const blue = "#12399d";
  const ink = "#172751";
  const paper = "#fff7e7";
  const orange = "#e8562d";
  const sans = '"Microsoft YaHei UI", "PingFang SC", sans-serif';

  function line(text, x, y, size, color = ink, weight = 600, max = 960) {
    ctx.fillStyle = color;
    ctx.font = weight + " " + size + "px " + sans;
    ctx.textBaseline = "top";
    const characters = Array.from(String(text));
    let fitting = characters.join("");
    while (ctx.measureText(fitting).width > max && characters.length) {
      characters.pop();
      fitting = characters.join("") + "…";
    }
    ctx.fillText(fitting, x, y);
  }

  function rule(y) {
    ctx.strokeStyle = "#9aa8ca";
    ctx.beginPath();
    ctx.moveTo(54, y);
    ctx.lineTo(1026, y);
    ctx.stroke();
  }

  ctx.fillStyle = paper;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = blue;
  ctx.fillRect(0, 0, 1080, 104);
  line("武汉接线台", 54, 27, 45, paper, 900);
  line("数命 SPU 城市 AI 接待员", 641, 36, 27, paper);
  const cropHeight = art.naturalWidth * 440 / 1080;
  ctx.drawImage(art, 0, Math.max(0, (art.naturalHeight - cropHeight) * .15), art.naturalWidth, cropHeight,
    0, 104, 1080, 440);
  line("武汉路线对比", 54, 571, 84, blue, 900);
  const update = rows.find(row => row.change)?.change;
  if (update) line(update, 58, 684, 31);
  rule(753);
  rows.forEach((row, index) => {
    const {title, stats, arrivals} = row;
    const y = 777 + index * 215;
    line(stats.days + " 天", 57, y + 2, 57, blue, 900, 185);
    line(title, 248, y, 42, ink, 800, 773);
    line(stats.daily_stops.length > 1 ? "每天 " + stats.daily_stops.join(" / ") + " 站" : stats.stops + " 个游览站次",
      248, y + 65, 34);
    line("转场 " + routeTime.duration(stats.transfer_min), 248, y + 113, 30, blue);
    if (arrivals.length) line(arrivals[0], 248, y + 155, 25, ink, 700, 777);
    ctx.fillStyle = orange;
    ctx.fillRect(59, y + 98, 109, 8);
    rule(y + 191);
  });
  line("路线时间为估算。插画为 AI 绘制。", 54, canvas.height - 70, 26, ink, 500);
  const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("对比图生成失败");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "武汉接线台-路线对比.png";
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 30000);
}
