"""Independent assertions over saved public API evidence. Never calls a model or reuses its verdict."""
import argparse
import json
import statistics
from pathlib import Path


def score(case, turns):
    results = [r.get("result", {}) for r in turns]
    days = [r.get("days", {}) for r in results]
    def read_day(time, key="1"):
        return days[time].get(key, {})
    def arrival(card, target, deadline):
        return card.get("contract", {}).get("destination") == target and card["audit"]["arrival"] <= deadline
    def has_reference(r, id):
        return any(c.get("id") == id for c in r.get("citations", []))
    if case == "preview_after_other_question":
        proposed = results[1]["preview"]["1"]
        return {"actual_preview": set(proposed["order"]) == {"江汉关","黎黄陂路"},
                "unrelated_answer": any(term in results[2]["answer"] for term in ("早餐","早饭")),
                "pending_after_question": results[2].get("has_pending_preview") is True,
                "official_preserved": read_day(1) == read_day(2) == results[0]["cards"]["1"],
                "same_preview_adopted": read_day(3) == proposed and not results[3]["has_pending_preview"]}
    if case == "walk_check_then_replan":
        old, final = read_day(0), read_day(2)
        legs = final["audit"]["legs"]
        unchanged = final == old
        return {"original_route": old["contract"]["origin"] == "江汉关" and old["contract"]["start"] == 840
                                  and "巴公房子" in old["order"] and arrival(old,"江汉路",990),
                "read_only": old == read_day(1),
                "preserved_appointment": arrival(final,"江汉路",990) and "巴公房子" in final["order"],
                "limits_or_explicit_conflict": (unchanged and any(term in results[2]["answer"] for term in
                    ("排不","保留","原样","保持","无法","没改","改不了","不能"))) or (bool(legs) and all(
                    leg["mode"] == "walk" and leg.get("walk_m") is not None and leg["walk_m"] <= 400
                    and not leg.get("estimated") for leg in legs))}
    if case == "map_adopt":
        original = results[0]["cards"]["1"]
        proposed = results[1]["preview"]["1"]
        return {"exact_remaining_stops": set(proposed["order"]) == set(original["order"]) - {"江汉关"},
                "protected_until_adopt": original == read_day(1) == read_day(2),
                "view_same_preview": results[2]["preview"]["1"] == proposed,
                "adopt_same_card": read_day(3) == proposed}
    if case == "move_with_more_time":
        old, new = days[1], days[2]
        return {"original_map_kept": old["1"] == results[0]["cards"]["1"],
                "correct_clocks": (new["1"]["contract"]["start"], new["2"]["contract"]["end"]) == (600,1260),
                "source_stops": set(new["1"]["order"]) == set(old["1"]["order"]) - {"黎黄陂路"},
                "destination_stops": set(new["2"]["order"]) == set(old["2"]["order"]) | {"黎黄陂路"},
                "audited": all(not v["audit"]["violations"] for v in new.values())}
    if case == "extend_from_tail":
        old, extended, second = read_day(0), read_day(1), read_day(2, "2")
        n = len(old["order"])
        return {"untouched_morning": extended["audit"]["stops"][:n] == old["audit"]["stops"],
                "added_after_rest": len(extended["order"]) == n + 1 and extended["audit"]["stops"][n]["start"] >= 900,
                "unchanged_on_append": extended == read_day(2),
                "correct_origin": second["contract"]["origin"] == "吉庆街",
                "persistent_exclusion": all("黄鹤楼" in card["contract"]["exclude"] for card in [old, extended, second])}
    if case in ("day_scope", "dated_exception"):
        place = "湖北省博物馆" if case == "day_scope" else "黄鹤楼"
        first, second = read_day(0), read_day(1, "2")
        checks = {"initial_anchor_date": first["contract"]["date"] == "2026-11-24",
                  "untouched_first_day": first == read_day(1),
                  "next_calendar_day": second.get("contract", {}).get("date") == "2026-11-25",
                  "deferred_visit_present": place in second.get("order", [])}
        if case == "day_scope":
            checks["departure_anchor"] = second.get("contract", {}).get("origin") == "江汉路"
            scoped = set(first["contract"]["exclude"])
            checks["day_one_category_only"] = ("湖北省博物馆" in scoped and not scoped.intersection(
                second.get("contract", {}).get("exclude", [])))
        else:
            checks["excluded_from_first_day"] = place not in first["order"]
        return checks
    if case == "catch_train":
        c = read_day(0)
        return {"departure": (c["contract"]["start"], c["contract"]["origin"]) == (780, "户部巷"),
                "must_visit": "黄鹤楼" in c["order"], "arrive_in_time": arrival(c, "汉口站", 990),
                "inquiry_does_not_write": c == read_day(1)}
    if case == "preview":
        first = read_day(0)
        options = [d["cards"]["1"] for d in results[1].get("deliverables", []) if d.get("cards")]
        pending = (results[1].get("preview") or {}).get("1")
        variants = options + ([pending] if pending else [])
        morning_baselines = [c for c in options if c["contract"]["start"] == 540]
        return {"official_unchanged": first == read_day(1), "real_10am_preview": any(c["contract"]["start"] == 600 for c in variants),
                "any_claimed_9am_baseline_matches_original": all(c["order"] == first["order"] and c["audit"]["stops"] == first["audit"]["stops"] for c in morning_baselines),
                "original_after_declining": read_day(2) == first,
                "decision_clears_pending": results[2].get("has_pending_preview") is False}
    if case == "map_to_chat":
        card = results[1]["cards"]["1"]
        order = card["order"]
        answer = results[3].get("answer", "")
        positions = [answer.find(n) for n in order]
        return {"fresh_map_edit": "吉庆街" in order and "江汉关" not in order,
                "stale_change_rejected": turns[2]["http"] == 409, "persisted_card_agrees": card == read_day(3),
                "answer_follows_saved_order": min(positions) >= 0 and sorted(positions) == positions and "江汉关" not in answer}
    if case == "hard_transport":
        first = read_day(0)
        return {"allowed_modes_only": all(l["mode"] in ("walk", "metro") for l in first["audit"]["legs"]),
                "both_places": {"黎黄陂路", "汉口江滩"} <= set(first["order"]),
                "read_only": first == read_day(1),
                "uncertainty_disclosed": any(term in results[1]["answer"] for term in ("估不准", "不确定", "估算", "估的", "无法", "核实"))}
    if case == "two_options":
        options = [d for d in results[0].get("deliverables", []) if d.get("cards")]
        short, long = sorted(options, key=lambda d: len(d["cards"]))
        edits = results[1].get("deliverables", [])
        edited = next(d for d in edits if d.get("cards") and d.get("option_id") == long["option_id"])
        compare = next(d for d in edits if d["kind"] == "compare")
        refs = {v["option_id"]: v["version"] for v in compare["versions"]}
        return {"two_options": [len(short["cards"]), len(long["cards"])] == [1, 2],
                "frozen_day": long["cards"]["1"] == edited["cards"]["1"], "train": arrival(edited["cards"]["2"], "汉口站", 960),
                "comparison_binds_versions": refs == {short["option_id"]: short["version"], edited["option_id"]: edited["version"]} and edited["version"] > long["version"]}
    if case == "official":
        a, b = [r["answer"] for r in results]
        return {"breakfast": "早餐" in a or "早饭" in a, "locations": "智民里" in a and "光谷" in a,
                "community_evidence": any(c.get("id", "").startswith("community.") for c in results[0].get("citations", [])),
                "submission": "项目简介" in b and "视频" in b and "选填" in b and has_reference(results[1], "register"),
                "separate_deadlines": "23:59:59" in b and ("公告" in b or "公布" in b) and has_reference(results[1], "deadline")}
    if case == "handoff":
        initial = results[0]["cards"]["1"]
        return {"map_day_preserved": read_day(1) == initial,
                "new_day_correct": read_day(1, "2")["contract"]["origin"] == "汉口站" and "古琴台" in read_day(1, "2")["order"],
                "moved_to_other_day": "黎黄陂路" in read_day(2, "2")["order"] and "黎黄陂路" not in read_day(2)["order"],
                "start_also_changed": read_day(2)["contract"]["start"] == 600}
    raise ValueError(case)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    cases = json.loads((args.folder / "manifest.json").read_text(encoding="utf8"))["cases"]
    verdicts, latencies, decisions, calls_by_case = {}, [], [], {}
    for case, questions in cases.items():
        try:
            rows = json.loads((args.folder / (case + ".json")).read_text(encoding="utf8"))
            if len(rows) != len(questions) or any("result" not in row for row in rows):
                raise ValueError("Incomplete run")
            for row in rows:
                if not row["question"].startswith("@"):
                    latencies.append(row["elapsed_s"])
                    decisions.append(sum(e["event"] == "step" for e in row["events"]))
                    calls_by_case.setdefault(case, []).append(row["result"].get("model_calls_this_request"))
            checks = score(case, rows)
            checks["responses_complete"] = all(
                row["http"] == (409 if row["question"] == "@stale_map" else 200)
                and (row["question"].startswith("@") or (row["result"].get("answer") and not row["result"].get("degraded")))
                for row in rows)
            verdicts[case] = {"pass": all(checks.values()), "checks": checks}
        except (ValueError, IndexError, TypeError, KeyError, StopIteration, FileNotFoundError) as exc:
            verdicts[case] = {"pass": False, "ungraded": str(exc)}
    report = {"cases": verdicts, "complete_chat_turns": len(latencies),
              "chat_median_seconds": statistics.median(latencies) if latencies else None,
              "chat_max_seconds": max(latencies, default=None), "stream_step_counts": decisions,
              "model_calls_by_case": calls_by_case}
    (args.folder / "grades.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf8")
    return 0 if all(v["pass"] for v in verdicts.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
