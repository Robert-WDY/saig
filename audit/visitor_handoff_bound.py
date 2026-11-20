"""Independent lower bound for the frozen crowded-day visitor journey, using its saved card."""
import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from places import PLACES
from transport import choose


def inspect(turns):
    days = turns[1]["result"]["days"]
    card = days["2"]
    c = card["contract"]
    stops = list(dict.fromkeys(card["order"] + ["黎黄陂路"]))
    if len(stops) > 12 or c.get("mobility", {}).get("rules") or c["destination"]:
        raise ValueError("此离线下界只核对不含日期交通规则、指定终点的原始样本。")
    if not c["origin"]:
        raise ValueError("缺少可核验的起点")
    mobility = {"rules": [], "default_preference": "fastest"}

    @lru_cache(None)
    def fastest(a, b):
        # Even an incompatible combination of cheapest legs is allowed here.
        # That deliberately underestimates the duration of any feasible itinerary.
        return min(choose(a, b, mobility, minute, {}, strict=True)["minutes"]
                   for minute in range(c["start"], c["end"] + 1))

    times = {(0, c["origin"]): c["start"]}
    for _ in stops:
        next_times = {}
        for (mask, last), now in times.items():
            for i, stop in enumerate(stops):
                bit = 1 << i
                if mask & bit:
                    continue
                key = (mask | bit, stop)
                at = now + fastest(last, stop) + c["durations"].get(stop, PLACES[stop]["minutes"])
                next_times[key] = min(next_times.get(key, at), at)
        times = next_times
    earliest = min(times.values()) + c.get("buffer", 0)
    after = turns[2]["result"]
    return {"budget_end": c["end"], "optimistic_finish": earliest, "over_budget_even_without_opening_windows": earliest > c["end"],
            "both_cards_unchanged": after["days"] == days, "target_stops_including_move": stops,
            "reply": after["answer"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    folder = parser.parse_args().folder
    report = inspect(json.loads((folder / "handoff.json").read_text(encoding="utf8")))
    (folder / "handoff-bound.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
