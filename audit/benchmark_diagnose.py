"""Counterfactuals at a known-good intermediate state. These are diagnosis, separate from E2E scores."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
from http.server import ThreadingHTTPServer

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import Agent
from audit_visitors import fixture
from serve import handler


def run(path):
    spec = json.loads(Path(__file__).with_name("benchmark-spec.json").read_text(encoding="utf8"))
    questions = {key: q for _, turns in spec["journeys"] for key, q, _ in turns}
    state = fixture()
    del state["days"]["2"]
    pending = deepcopy(state["days"])
    pending["1"]["contract"]["start"] = 660
    for stop in pending["1"]["audit"]["stops"]:
        stop["start"] += 120
        stop["end"] += 120
    pending["1"]["audit"]["arrival"] += 120
    state["pending_days"] = pending
    state["turns"] = [{"user":questions["preview"], "answer":"备选第1天 11:00 从江汉路出发。正式行程仍是 09:00。"}]
    rows = []
    with tempfile.TemporaryDirectory() as d:
        a = Agent(str(Path(d)/"sessions.sqlite"))
        api = ThreadingHTTPServer(("127.0.0.1",0),handler(a))
        Thread(target=api.serve_forever,daemon=True).start()
        try:
            for key in ("inspect","adopt"):
                a.store.save(key,"seed","seed",0,state,{})
                r = requests.post(f"http://127.0.0.1:{api.server_port}/chat",
                                  json={"session":key,"query":questions[key]},timeout=300)
                r.raise_for_status()
                actual = r.json()
                _, after, _ = a.store.read(key,"inspect","inspect")
                if key == "inspect":
                    checks = {"saved_unchanged":after["days"]==state["days"], "pending_unchanged":after.get("pending_days")==pending,
                              "states_11":any(t in actual["answer"] for t in ("11:00","11点","十一点","十一时","11时"))}
                else:
                    checks = {"exact_commit":after["days"]==pending, "consumed":not after.get("pending_days")}
                rows.append({"probe":key,"checks":checks,"passed":all(checks.values()),"result":actual,"after":after})
                path.write_text(json.dumps({"controlled_state":state,"observations":rows},ensure_ascii=False,indent=2),encoding="utf8")
        finally:
            api.shutdown()
            api.server_close()


if __name__=="__main__":
    run(Path(sys.argv[1]))
