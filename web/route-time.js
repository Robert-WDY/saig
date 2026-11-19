"use strict";

// Estimates are rounded at display time. Route validation keeps exact minutes.
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
    const window = contract.windows?.[stop.place] || [-Infinity, Infinity];
    return this.visit(stop.start, stop.end, Math.max(contract.start ?? -Infinity, window[0]),
      Math.min(Number.isFinite(contract.end) ? contract.end - (contract.buffer || 0) : Infinity, window[1]));
  },
  arrival(minutes, deadline) {
    if (!Number.isFinite(minutes)) return "时间待核实";
    const rounded = Math.ceil(minutes / 10) * 10;
    return this.exact(Number.isFinite(deadline) && rounded > deadline ? minutes : rounded);
  },
  change(previous, updated) {
    const clock = card => this.arrival(card.audit.arrival, card.contract.end - (card.contract.buffer || 0));
    const end = clock(updated);
    const label = updated.contract.destination ? "抵达" + updated.contract.destination : "结束游览";
    if (!previous) return "预计约 " + end + " " + label;
    const old = clock(previous);
    const delta = updated.audit.arrival - previous.audit.arrival;
    if (!delta) return "预计约 " + end + " " + label + "，结束时间不变";
    if (old === end) return "预计仍约 " + end + " " + label + "，精算时刻略有" + (delta > 0 ? "延后" : "提前");
    return label + (delta > 0 ? "延后" : "提前") + "，约 " + old + " → " + end;
  },
  duration(minutes) {
    if (!Number.isFinite(minutes)) return "时间待核实";
    if (minutes === 0) return "0 分钟";
    if (minutes < 5) return "不到 5 分钟";
    return "约 " + Math.max(10, Math.round(minutes / 10) * 10) + " 分钟";
  }
};
