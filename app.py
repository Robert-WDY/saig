"""CLI for the reception backend. Run from any directory."""
import argparse
import json
import os
from pathlib import Path
import sys
from agent import Agent
from knowledge import Knowledge, TOOLS, grounded
from model import Model
from places import locate

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["chat","tool","rag"])
    p.add_argument("query")
    p.add_argument("--tool",choices=list(TOOLS)+["location"],default="wuhan")
    p.add_argument("--session",default="local-demo")
    p.add_argument("--request-id")
    p.add_argument("--db",default=os.getenv("SAIG_DB",str(Path(__file__).parent/"sessions.sqlite")))
    a=p.parse_args()
    if a.action=="chat":
        result=Agent(a.db).respond(a.session,a.query,a.request_id)
    elif a.tool=="location":
        result=locate(a.query)
    else:
        evidence=Knowledge().search(a.query,TOOLS[a.tool])
        result=evidence if a.action=="tool" else grounded(Model(),a.query,evidence)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
