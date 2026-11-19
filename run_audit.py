"""Run the acceptance suites on the working tree in private sessions. Never overwrite evidence."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread

from agent import Agent
from model import Model
from serve import handler

ROOT=Path(__file__).resolve().parent

def run(out):
    out.mkdir(parents=True,exist_ok=False)
    scripts=["audit_layers","audit_adapters","eval_rag","audit_visitors","audit_transfer","audit_dissatisfaction","eval_agent","audit_handoffs","audit_evidence"]
    files=sorted([*ROOT.glob("*.py"),*ROOT.joinpath("data").glob("*.jsonl"),
                  *(p for p in (ROOT/"data").glob("*.json") if not p.name.startswith("eval-"))])
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    manifest={"started":datetime.now(timezone.utc).isoformat(),"source_sha256":hashes,
              "model":Model().name,"suites":{}}
    def save():
        (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf8")
    save()
    with tempfile.TemporaryDirectory() as tmp:
        api=ThreadingHTTPServer(("127.0.0.1",0),handler(Agent(str(Path(tmp)/"api.db"))))
        Thread(target=api.serve_forever,daemon=True).start()
        base="http://127.0.0.1:"+str(api.server_port)
        def suite(name):
            cmd=[sys.executable,*(["-m","unittest","-v","test_backend"] if name=="unit" else
                                 [str(ROOT/(name+".py")),"--out",str(out/(name+".json"))])]
            if name in ("audit_layers","audit_adapters"):cmd+=["--base",base]
            elif name=="eval_rag":cmd+=["--live"]
            elif name=="audit_handoffs":cmd+=[str(out/"audit_visitors.json")]
            with (out/(name+".log")).open("w",encoding="utf8") as log:
                rc=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                                  env={**os.environ,"PYTHONIOENCODING":"utf8"}).returncode
            return {"process_exit":rc}
        try:
            # One uninterrupted visitor suite and a sequential lane for smaller suites, sharing a local model.
            with ThreadPoolExecutor(max_workers=2) as pool:
                visitors=pool.submit(suite,"audit_visitors")
                for name in ["unit","audit_adapters","audit_layers","audit_transfer","audit_dissatisfaction","eval_agent","eval_rag","audit_evidence"]:
                    manifest["suites"][name]=suite(name);save()
                manifest["suites"]["audit_visitors"]=visitors.result()
            manifest["suites"]["audit_handoffs"]=suite("audit_handoffs")
        finally:
            api.shutdown();api.server_close()
            manifest["finished"]=datetime.now(timezone.utc).isoformat()
            save()
    # Scripts preserve all failed rows; a completed process can still indicate a failed business gate.
    failed=False
    for name in scripts:
        p=out/(name+".json")
        if not p.exists():
            failed=True
            continue
        records=json.loads(p.read_text(encoding="utf8"))
        if name=="eval_rag":
            bits=[r["answer_check"] and (not r["has_gold"] or r["rank"] is not None) for r in records["cases"]]
        elif name=="audit_handoffs":
            bits=[r["accepted"] for r in records["rows"]]+list(records["deliberate_corruptions_rejected"].values())
        else:
            bits=[r["passed"] for r in records]
        manifest["suites"][name].update(passed=sum(bits),observed=len(bits))
        if not all(bits):failed=True
    if all((out/name).exists() for name in ("audit_handoffs.json","audit_transfer.json","audit_dissatisfaction.json")):
        from audit_review import evaluate
        strict=evaluate(out)
        travel=strict["delegated_breakfast_quality"]
        checks={k:r["accepted"] for k,r in strict["transfer"].items()}
        checks.update({k:r["passed"] for k,r in strict["journeys"].items()})
        checks["feasible_lower_travel_alternative"]=bool(travel and not travel["same_contract_violations"]
            and travel["breakfast_evidence"] and travel["delivered_travel"]<=travel["comparison_travel"])
        manifest["strict_review"]=checks
        failed=failed or not all(checks.values())
    manifest["business_gate"]="failed" if failed or any(t["process_exit"] for t in manifest["suites"].values()) else "passed"
    save()
    return int(manifest["business_gate"]=="failed")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True)
    sys.exit(run(p.parse_args().out.resolve()))
