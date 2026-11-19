"""Repeat the first failed original request in three empty, isolated sessions; retain model decisions."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import Agent


def run(out):
    original=json.loads((ROOT/"audit/release-1118-final/eval_agent.json").read_text(encoding="utf8"))[0]
    rows=[]
    with tempfile.TemporaryDirectory() as tmp:
        for trial in range(3):
            a=Agent(str(Path(tmp)/f"{trial}.sqlite"))
            ask=a.model.ask
            calls=[]
            def observe(instruction,payload,*args,**kwargs):
                actual=ask(instruction,payload,*args,**kwargs)
                calls.append({"instruction":instruction,"input":payload,"result":actual})
                return actual
            a.model.ask=observe
            r=a.respond("visitor",original["input"])
            c=r["days"].get("1",{}).get("contract",{})
            ok=c.get("origin")=="江汉路" and c.get("start")==540 and c.get("end")==780 and "智民里" in c.get("must",[])
            rows.append({"trial":trial+1,"input":original["input"],"passed":ok,"result":r,"calls":calls})
            out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")


if __name__=="__main__":
    run(Path(sys.argv[1]))
