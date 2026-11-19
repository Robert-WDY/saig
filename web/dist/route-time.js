"use strict";
const routeTime = {
  exact(minutes) {
    if (!Number.isFinite(minutes)) return "时间待核实";
    return String(Math.floor(minutes / 60)).padStart(2, "0") + ":" + String(minutes % 60).padStart(2, "0");
  },
  visit(start, end, earliest = -Infinity, latest = Infinity) {
    if (!Number.isFinite(start) || !Number.isFinite(end)) return "时间待核实";
    const first = Math.min(latest, 1440, Math.max(earliest, Math.round(start / 10) * 10));
    const last = Math.min(latest, 1440, Math.round(end / 10) * 10);
    return last > first ? "约 " + this.exact(first) + "–" + this.exact(last) : "约 " + this.exact(first);
  },
  stop(stop, contract) {
    var _a, _b;
    const window = ((_a = contract.windows) == null ? void 0 : _a[stop.place]) || [-Infinity, Infinity];
    return this.visit(
      stop.start,
      stop.end,
      Math.max((_b = contract.start) != null ? _b : -Infinity, window[0]),
      Math.min(Number.isFinite(contract.end) ? contract.end - (contract.buffer || 0) : Infinity, window[1])
    );
  },
  arrival(minutes, deadline) {
    if (!Number.isFinite(minutes)) return "时间待核实";
    const rounded = Math.ceil(minutes / 10) * 10;
    return this.exact(Number.isFinite(deadline) && rounded > deadline ? minutes : rounded);
  },
  duration(minutes) {
    if (!Number.isFinite(minutes)) return "时间待核实";
    if (minutes === 0) return "0 分钟";
    if (minutes < 5) return "不到 5 分钟";
    return "约 " + Math.max(10, Math.round(minutes / 10) * 10) + " 分钟";
  }
};
