"""Apply hard contracts, then combine with evidence-bound semantic review."""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attached(citation, candidates, answer):
    item = candidates.get(citation["id"], {})
    return bool(item and citation.get("claim") and citation["claim"] in answer
                and citation.get("quote") and citation["quote"] in item["text"]
                and citation.get("source") == item.get("source")
                and citation.get("locator") == item.get("locator"))


def contract(key, record):
    p, after, before = record["payload"], record["after"], record["before"]
    checks = {"http": record["status"] == 200, "stored_card": p.get("days") == after["days"],
              "stored_facts": p.get("facts") == after["facts"],
              "revision": record["revisions"][1] == p.get("revision") == record["revisions"][0]+1}
    days = after["days"]
    card = days.get("1", next(iter(days.values()), {}) if len(days) == 1 else {})
    c = card.get("contract", {})
    if key in {"base", "train", "pickup"}:
        checks["one_day_with_correct_identity"] = set(days) == {"1"}
        checks["origin"] = c.get("origin") == "江汉路"
        checks["required_visit"] = "智民里" in c.get("must", []) and "智民里" in card.get("order", [])
        checks["start"] = c.get("start") == (540 if key == "base" else 600)
        if key == "base":
            checks["end"] = c.get("end") == 1020
        else:
            latest = 870 if key == "train" else 900
            checks["endpoint"] = c.get("destination") == "汉口站"
            checks["effective_deadline"] = c.get("end", 0)-c.get("buffer", 0) == latest
            checks["arrival"] = card.get("audit", {}).get("arrival", 1440) <= latest
            if key == "pickup":
                checks["order_preserved"] = card.get("order") == before["days"].get("1", {}).get("order")
    if key in {"preview", "inspect"}:
        pending = after.get("pending_days", {})
        checks["protected"] = bool(before["days"]) and after["days"] == before["days"]
        checks["pending_11"] = pending.get("1", {}).get("contract", {}).get("start") == 660
        if key == "preview":
            checks["shown"] = bool(pending) and p.get("preview") == pending
            checks["same_trip_days"] = set(pending) == set(before["days"])
            old = before["days"].get("1", {})
            new = pending.get("1", {})
            checks["only_start_changed"] = bool(old) and new.get("contract") == {**old.get("contract", {}), "start": 660}
        else:
            checks["same_preview"] = bool(pending) and pending == before.get("pending_days")
    if key == "adopt":
        checks["exact_commit"] = bool(before.get("pending_days")) and after["days"] == before["pending_days"] and not after.get("pending_days")
    if key in {"family", "correct", "both"}:
        expected = {"self": "阿岚", "self.mother": "阿宁"} if key == "family" else {"self": "阿宁", "self.mother": "阿岚"}
        names = [(f["subject"], f["object"]) for f in after["facts"] if f["relation"] == "name"]
        checks["names"] = sorted(names) == sorted(expected.items())
    if key in {"compound", "private"}:
        checks["likes"] = any(f["subject"] == "self" and "老建筑" in f["object"] for f in after["facts"])
    if key in {"private", "both", "map", "scope"}:
        checks["read_only"] = all(before.get(k) == after.get(k) for k in ("days", "facts", "pending_days"))
    return checks


def evaluate(archive, review_path):
    spec = read(Path(__file__).with_name("benchmark-spec.json"))
    reviews = read(review_path)
    rows = {}
    retrieval = {}
    def add(key, file, hard):
        entry = reviews.get(key, {})
        evidence_ok = entry.get("sha256") == digest(file) and bool(entry.get("reason"))
        semantic = entry.get("verdict", "unknown") if evidence_ok else "unknown"
        status = "fail" if not all(hard.values()) or semantic == "fail" else semantic
        rows[key] = {"hard": hard, "semantic": semantic, "status": status,
                     "reason": entry.get("reason"), "evidence": file.name, "sha256": digest(file)}
    for _, turns in spec["journeys"]:
        for key, _, _ in turns:
            file = archive/(key+".json")
            add(key, file, contract(key, read(file)))
    for key, _, _, slots, _ in spec["retrieval"]:
        file = archive/(key+".json")
        pair = read(file)
        candidates = {r["id"]:r for r in pair["retrieval"]["payload"]}
        p = pair["generation"]["payload"]
        citations = p.get("citations", [])
        ranks = [next((i for i, n in enumerate(candidates, 1) if n in group), None) for group in slots]
        used = {c["id"] for c in citations}
        retrieval[key] = {"slot_ranks": ranks, "cited_ids": sorted(used), "returned_ids": list(candidates)}
        hard = {"http": pair["retrieval"]["status"] == pair["generation"]["status"] == 200,
                "anchor": all(attached(c, candidates, p["answer"]) for c in citations),
                "slots_in_top5": all(rank is not None for rank in ranks),
                "slots_cited": all(used.intersection(group) for group in slots) if slots else not used}
        add(key, file, hard)
    journeys = {sid:all(rows[key]["status"] == "pass" for key, _, _ in turns) for sid, turns in spec["journeys"]}
    return {"rows": rows, "journeys": journeys, "retrieval": retrieval,
            "accepted": all(r["status"] == "pass" for r in rows.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("review", type=Path)
    args = parser.parse_args()
    result = evaluate(args.archive, args.review)
    (args.archive/"assessment.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    raise SystemExit(0 if result["accepted"] else 1)
