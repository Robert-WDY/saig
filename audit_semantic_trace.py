"""Capture model decisions for the failing editing submodule, using a public synthetic itinerary."""
import argparse
import json
from pathlib import Path
from agent import Agent
from audit_visitors import CASES, fixture
from model import Model
import tempfile

class TraceModel(Model):
    def __init__(self):
        super().__init__()
        self.log=[]
    def ask(self,instruction,payload,*args,**kwargs):
        r=super().ask(instruction,payload,*args,**kwargs)
        self.log.append({"stage":instruction.splitlines()[0],"result":r})
        return r

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("ids",nargs="+")
    args=p.parse_args();rows=[]
    with tempfile.TemporaryDirectory() as tmp:
        model=TraceModel();a=Agent(str(Path(tmp)/"session.db"),model=model)
        for i,q,*_ in CASES:
            if i in args.ids:
                model.log=[]
                try: result=a.understand(q,fixture())
                except Exception as err: result={"error":repr(err)}
                rows.append({"id":i,"input":q,"semantic_result":result,"stages":model.log})
                args.out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
