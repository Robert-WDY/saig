"""Capture real requests and states. Scoring instructions never enter the HTTP payload."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from http.server import ThreadingHTTPServer
from threading import Thread

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import Agent
from serve import handler

SPEC = Path(__file__).with_name("benchmark-spec.json")


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf8")


def capture(out):
    spec = json.loads(SPEC.read_text(encoding="utf8"))
    out.mkdir(parents=True, exist_ok=False)
    files = sorted([*ROOT.glob("*.py"), *ROOT.joinpath("data").glob("*.jsonl"),
                    *(p for p in (ROOT/"data").glob("*.json") if not p.name.startswith("eval-")), SPEC, Path(__file__)])
    write(out/"inputs.json", {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    with tempfile.TemporaryDirectory() as tmp:
        agent = Agent(str(Path(tmp)/"evaluation.sqlite"))
        api = ThreadingHTTPServer(("127.0.0.1", 0), handler(agent))
        Thread(target=api.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{api.server_port}"
        def call(endpoint, body):
            start = time.monotonic()
            response = requests.post(url+endpoint, json=body, timeout=450)
            return {"request": body, "status": response.status_code, "seconds": round(time.monotonic()-start, 2),
                    "payload": response.json()}

        def journey(item):
            sid,turns=item
            for key, question, _ in turns:
                rev0, before, _ = agent.store.read(sid, "observe", "")
                result = call("/chat", {"session": sid, "request_id": key, "query": question})
                rev1, after, _ = agent.store.read(sid, "observe", "")
                write(out/(key+".json"), {**result, "before": before, "after": after, "revisions": [rev0, rev1]})
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(journey,spec["journeys"]))
            for key, tool, question, _, _ in spec["retrieval"]:
                body = {"tool": tool, "query": question}
                candidates = call("/tool", body)
                answer = call("/rag", body)
                write(out/(key+".json"), {"retrieval": candidates, "generation": answer})
        finally:
            api.shutdown()
            api.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    capture(parser.parse_args().out)
