"""Final, previously unexecuted traveler tasks. Do not use for prompt development."""
import json
from pathlib import Path
import sys,tempfile
from agent import Agent
from audit_visitors import fixture

def run(out):
    results=[]
    with tempfile.TemporaryDirectory() as d:
        a=Agent(str(Path(d)/"s.db"))
        def call(sid,case,q,judge):
            before=a.store.read(sid,"inspect","inspect")[1]
            try:
                r=a.respond(sid,q)
                passed=judge(before,r)
            except Exception as e:
                r={"error":repr(e)};passed=False
            results.append(dict(case=case,input=q,result=r,passed=bool(passed)))
            out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf8")
        call("friends","两个同行者喜好各自归属","请记住：我喜欢看江景，我妈妈喜欢逛博物馆。",
             lambda b,r:any("博物馆" in f["object"] and "mother" in f["subject"] for f in r["facts"]) and
                        any("江景" in f["object"] and f["subject"]=="self" for f in r["facts"]))
        call("friends","第三人回忆不带出本人的喜好","替妈妈确认一下，我之前说她喜欢哪类地方来着？",
             lambda b,r:r["facts"]==b["facts"] and "博物馆" in r["answer"] and "江景" not in r["answer"] and not r["citations"])
        a.store.save("remote","seed","seed",0,fixture(),{})
        call("remote","咨询期间保护另一份既有行程","有朋友想看我的参赛视频。独立标签栏怎么填，视频能只放体验网址吗？先别动我的两天行程。",
             lambda b,r:r["days"]==b["days"] and not r.get("preview") and "SAIG" in r["answer"] and "视频" in r["answer"]
                    and any(w in r["answer"] for w in ("必","不能","需要")) and bool(r["citations"]))
        call("stranger","独立会话拒绝回忆他人的关系","我妈妈喜欢去哪类景点？我以前告诉过你吗？",
             lambda b,r:not r["facts"] and "博物馆" not in r["answer"] and any(w in r["answer"] for w in ("没有","未","不清楚","不知道","未记录")))
    return all(r["passed"] for r in results)
if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--out",type=Path,required=True)
    sys.exit(not run(parser.parse_args().out))
