"""Establish feasibility with a known contract and isolate the subsequent pickup edit."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import Agent
from audit_visitors import fixture
from planning import evaluate


def run(out):
    spec=json.loads(Path(__file__).with_name("benchmark-spec.json").read_text(encoding="utf8"))
    q=next(t[1] for name,turns in spec["journeys"] if name=="transfer" for t in turns if t[0]=="pickup")
    seed=fixture()
    del seed["days"]["2"]
    card=seed["days"]["1"]
    card["contract"].update(start=600,end=900,destination="汉口站",buffer=30)
    card["audit"]=evaluate(card["contract"],card["order"])
    assert not card["audit"]["violations"]
    with tempfile.TemporaryDirectory() as tmp:
        a=Agent(str(Path(tmp)/"s.sqlite"))
        a.store.save("rail","seed","seed",0,seed,{})
        r=a.respond("rail",q)
        actual=a.store.read("rail","observe","")[1]["days"]["1"]
    expected={**card["contract"],"buffer":0}
    result={"before":card,"query":q,"result":r,"persisted":actual,
            "passed":actual["contract"]==expected and actual["order"]==card["order"]}
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")


if __name__=="__main__":
    run(Path(sys.argv[1]))
