"""Grade saved HTTP conversations against the published contract and a transcript-bound review."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from planning import evaluate
from benchmark_score import attached


def read(path):
    return json.loads(path.read_text(encoding="utf8"))


def checks(turn, step, documents):
    sid = turn["session"]
    p, old, new = (turn[k] for k in ("response", "before", "after"))
    citations = p.get("citations", [])
    result = {"answer_present": bool(p.get("answer")),
              "session": sid == p.get("session"),
              "published_state": all(p.get(k) == new[k] for k in ("days", "facts")),
              "anchors": all(attached(c, documents, p["answer"]) for c in citations)}
    card = new["days"].get("1", {})
    c = card.get("contract", {})
    if sid in {"overnight", "station"}:
        result.update(one_trip_day=set(new["days"]) == {"1"}, includes_required_stop="智民里" in c.get("must", []) and "智民里" in card.get("order", []),
                      origin=c.get("origin") == "江汉路")
        if card:
            audit = evaluate(c, card["order"])
            result["feasible"] = audit == card["audit"] and not audit["violations"]
        if sid == "station":
            result["appointment"] = (c.get("start"), c.get("end"), c.get("buffer"), c.get("destination")) == (540, 990, 0, "汉口站")
        else:
            result["published_time"] = (c.get("start"), c.get("end")) == (510, 840)
            result["weekday"] = card.get("calendar_label") in ("周日", "星期日", "星期天", "周天", "礼拜天", "礼拜日")
            if step > 1:
                pending = new.get("pending_days", {}).get("1", {})
                result["preview_only"] = new["days"] == old["days"] and pending.get("contract") == {**c, "start": 540}
                if pending:
                    verified = evaluate(pending["contract"], pending["order"])
                    result["preview_feasible"] = verified == pending["audit"] and not verified["violations"]
                if step == 2:
                    result["preview_disclosed"] = p.get("preview") == new.get("pending_days") and bool(pending)
                if step == 3:
                    result["both_snapshots_protected"] = new.get("pending_days") == old.get("pending_days")
    if sid == "screen":
        result["resident"] = any(f["subject"] == "self" and f["relation"] == "stays_at" and f["object"] == "江汉路" and f["quote"] and f["quote"] in "记住我住江汉路，再帮我查一下线上四项各多少分。" for f in new["facts"])
    if sid in {"debate", "hearsay", "brochure", "desk", "caption", "focus", "visitor-note", "station-query", "judge-link", "glossary", "observer", "narration"} or (sid == "screen" and step == 2):
        result["read_only"] = all(new.get(k) == old.get(k) for k in ("days", "facts", "pending_days"))
    if sid in {"debate", "hearsay", "brochure", "desk", "caption", "focus", "visitor-note", "station-query", "judge-link", "glossary", "observer", "narration"} or (sid == "screen" and step == 1):
        result["has_evidence"] = bool(citations)
    if sid=="private-empty":
        result["private_only"] = not citations and not new["facts"] and not new["days"]
    if sid=="arrival-check":
        result["read_only"] = all(new.get(k)==old.get(k) for k in ("days","facts","pending_days"))
    if sid=="visitor-name":
        result["name_bound"] = any(f["subject"]=="self" and f["object"]=="云帆" and f["quote"] and "云帆" in f["quote"] for f in new["facts"])
        if step==2:
            result["private_read_only"] = not citations and all(new.get(k)==old.get(k) for k in ("facts","days","pending_days"))
    return result


def grade(spec, capture, review, out):
    raw = read(capture)
    expected = read(spec)
    judgments = read(review)
    documents = read(ROOT/"data/official.json")
    documents.extend(json.loads(s) for s in (ROOT/"data/handbooks.jsonl").read_text(encoding="utf8").splitlines())
    documents = {r["id"]: r for r in documents}
    integrity = (raw["spec_sha256"] == sha256(spec.read_bytes()).hexdigest()
                 and judgments["capture_sha256"] == sha256(capture.read_bytes()).hexdigest()
                 and len(raw["turns"]) == len(expected) == len(judgments["turns"]))
    rows, steps = [], {}
    for (sid, question, criterion), turn, judgment in zip(expected, raw["turns"], judgments["turns"]):
        steps[sid] = steps.get(sid, 0) + 1
        hard = checks(turn, steps[sid], documents)
        hard["matched_input"] = (sid, question) == (turn["session"], turn["input"])
        rows.append({"question": question, "criterion": criterion, "checks": hard, "review": judgment,
                     "passed": all(hard.values()) and bool(judgment.get("reason")) and judgment.get("verdict") == "pass"})
    accepted = integrity and all(row["passed"] for row in rows)
    out.write_text(json.dumps({"accepted": accepted, "integrity": integrity, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf8")
    return accepted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("spec", "capture", "review", "out"):
        parser.add_argument(name, type=Path)
    sys.exit(not grade(**vars(parser.parse_args())))
