"""Run independent, isolated visitor journeys. Uses paid chat only with an explicit --base.
Save a frozen manifest before the first request and redacted per-turn evidence after each request.
Usage: python audit/visitor_acceptance.py --base https://your-site --out audit/visitor-run
"""
import argparse
import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests


CASES = {
    "map_adopt": [
        "@map_create",
        "江汉关门口我们已经拍过照了。先让我看看跳过这一站会怎么走，原路线留着。",
        "刚才那版我还没看清，再把备选的站点顺序给我看看。",
        "好，就用跳过江汉关的那版，把它作为正式安排。",
    ],
    "move_with_more_time": [
        "@map_create",
        "第二天想从汉口站坐车去古琴台，先按早九晚六给我排。",
        "我们换了晚一点的车。把第一天的黎黄陂路放到第二天，第二天可以逛到晚上九点。第一天改成十点才集合，其余地方都保留。",
    ],
    "extend_from_tail": [
        "先排一个汉口的上午，九点出发，下午一点半就收工，黄鹤楼这趟都不用安排。",
        "午休后还有空，三点再接着走一站，最晚晚上七点半结束。上午已经定的照旧。",
        "第二天就从吉庆街出来逛，把第二天也存下来。头一天我已经发给朋友了。",
    ],
    "dated_exception": [
        "11月24日先逛汉口老街，这一天别去黄鹤楼，留到过江那天。给我排好24号。",
        "11月25号再给我加一天，在户部巷过早后，想进黄鹤楼。24号那个安排照旧。",
    ],
    "day_scope": [
        "这周二（11月24日）在武汉玩一天。我今天不想看博物馆，就想逛黎黄陂路，下午四点结束。",
        "明天留给湖北省博物馆，从江汉路出发，给我多排这一天。昨天那条老街路线留着。",
    ],
    "catch_train": [
        "11月25日下午一点我在户部巷吃完饭出发，想去黄鹤楼。最晚下午四点半要到汉口站，我是去接人，不用预留进站时间。给我排这半天。",
        "如果还塞一个省博，四点半还能到吗？只帮我判断，先别改我的行程。",
    ],
    "map_to_chat": [
        "@map_create", "@map_replace", "@stale_map",
        "我刚在地图上换了一站。照现在存的行程，按顺序报一下要去哪几个地方，不用重新规划。",
    ],
    "preview": [
        "周二早上九点在江汉路集合，去黎黄陂路和汉口江滩散步，下午两点前结束。帮我排好。",
        "朋友可能睡懒觉。给我看一下十点出发的备选路线，先保留九点出发的原方案。",
        "朋友确认能早起，我们还是用原来九点出发的。报一下现在的出发时间。",
    ],
    "two_options": [
        "我在选住几晚。给我一个一日游，再给一个两日游，各自存成方案，比较一下哪套更适合第一次来武汉的人。",
        "我只想改住一晚的两日方案，第二天下午四点前要到汉口站。一日方案别动，再比较一下。",
    ],
    "hard_transport": [
        "陪我爸玩武汉，我们只能坐地铁或步行，不打车也不坐公交。周二九点从江汉路出发，想看黎黄陂路和汉口江滩，下午三点结束。",
        "爸爸说一段最多能走五百米。帮我核对刚才的行程，有一段估不准就告诉我，先别改。",
    ],
    "official": [
        "第一次来武汉，大家说的过早是什么意思？我也想顺路去数命 SPU 社区了解一下它是做什么的，在武汉哪个地方？",
        "我打算个人报名 SAIG。如果有产品网址，还必须交哪些东西？官网的人气榜截止时间就是交作品的截止时间吗？",
    ],
    "handoff": [
        "@map_create",
        "再排一天，从汉口站出发，下午六点前结束，第二天想去古琴台。",
        "把第一天的黎黄陂路挪到第二天；第一天剩下的景点我想十点才出发。这两处都帮我改好。",
    ],
}
EXPECTATIONS = {
    "map_adopt": "Original map card survives preview and readback; explicitly adopted card exactly matches the preview.",
    "move_with_more_time": "Single-turn move and two clock edits are atomic, preserve every other stop and pass both audits.",
    "extend_from_tail": "New afternoon stop after 15:00 with exact original timeline; day 2 departs at 吉庆街 and inherits trip-wide exclusion.",
    "dated_exception": "Nov 24 excludes 黄鹤楼; append Nov 25 visiting it, preserving Nov 24.",
    "day_scope": "Day 1 contains 黎黄陂路; day 2 starts at 江汉路 and visits 湖北省博物馆 on Nov 25; day 1 unchanged.",
    "catch_train": "Start 13:00 at 户部巷; include 黄鹤楼; audited arrival at 汉口站 <=16:30. Read-only follow-up preserves card.",
    "map_to_chat": "Replace 江汉关 with 吉庆街; stale map write receives HTTP 409; answer reports current order without removed stop.",
    "preview": "Start 09:00. Keep official day byte-for-byte during preview, provide inspectable 10:00 alternative; finally 09:00.",
    "two_options": "Two stored independent choices, 1 and 2 days, comparison. Modify only day 2 of longer choice, audited arrival <=16:00 at 汉口站.",
    "hard_transport": "Every selected leg walk or metro. Report whether each leg has evidence for 500m maximum or identify insufficient evidence; inquiry read-only.",
    "official": "Address three parts: 过早, community purpose, location. Second reply includes project synopsis + demo, optional product link, separate deadlines with support.",
    "handoff": "Keep map day; add day 2 at 汉口站 visiting 古琴台. Finally move 黎黄陂路 once and update day 1 start to 10:00 in same turn.",
}


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf8")


def call(s, base, sid, question, history):
    started = time.monotonic()
    body = {"session": sid, "request_id": uuid.uuid4().hex}
    events = []
    if question.startswith("@"):
        if question == "@map_create":
            change = {"plan": "new", "day": "1", "add": ["江汉关", "黎黄陂路", "巴公房子"], "remove": []}
        else:
            first = history[0]["result"]["cards"]["1"]
            change = {"plan": "current", "day": "1", "basis": {k: first[k] for k in ("order", "contract")},
                      "add": ["吉庆街"], "remove": ["江汉关"]}
        r = s.post(base + "/route-edit", json={**body, "change": change}, timeout=(8, 55))
        result = r.json()
    else:
        result = {}
        with s.post(base + "/chat/stream", json={**body, "query": question}, timeout=(10, 130), stream=True) as r:
            if r.ok:
                kind = ""
                for line in r.iter_lines(chunk_size=1024):
                    if line.startswith(b"event: "):
                        kind = line[7:].decode()
                    elif line.startswith(b"data: "):
                        data = json.loads(line[6:])
                        if kind in ("result", "error"):
                            result = data
                        elif kind in ("tool", "tool_done", "step"):
                            events.append({"event": kind, **data})
            else:
                result = r.json()
    result.pop("session", None)
    result.pop("request_id", None)
    return {"question": question, "http": r.status_code, "elapsed_s": round(time.monotonic()-started, 2),
            "events": events, "result": result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", choices=CASES, nargs="+", default=list(CASES))
    args = parser.parse_args()
    base = args.base.rstrip("/")
    args.out.mkdir(parents=True, exist_ok=False)
    s = requests.Session()
    s.trust_env = False
    s.headers["Origin"] = base
    js = s.get(base + "/web/chat.js", timeout=10)
    js.raise_for_status()
    save(args.out / "manifest.json", {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
          "started_utc": datetime.now(timezone.utc).isoformat(), "base": base,
          "js_sha256": hashlib.sha256(js.content).hexdigest(),
          "cases": {k: CASES[k] for k in args.cases}, "acceptance": {k: EXPECTATIONS[k] for k in args.cases}})
    next_chat = 0
    for case in args.cases:
        sid = uuid.uuid4().hex
        history = []
        path = args.out / (case + ".json")
        try:
            for i, q in enumerate(CASES[case], 1):
                if not q.startswith("@"):
                    time.sleep(max(0, next_chat - time.monotonic()))
                    next_chat = time.monotonic() + 9
                row = call(s, base, sid, q, history)
                history.append(row)
                save(path, history)
                print(case, i, row["http"], row["result"].get("mode"), row["elapsed_s"], flush=True)
                if row["http"] >= 400 and q != "@stale_map":
                    break
        except (requests.RequestException, ValueError, KeyError) as exc:
            history.append({"error": str(exc), "question": q})
            save(path, history)
        finally:
            response = s.post(base + "/session/delete", json={"session": sid}, timeout=15)
            print(case, "cleanup", response.status_code, flush=True)


if __name__ == "__main__":
    main()
