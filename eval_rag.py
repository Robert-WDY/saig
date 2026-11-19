"""Evaluate retrieval independently of intent routing, then optionally exercise grounded generation."""
import argparse
import json
import sys
from pathlib import Path
from knowledge import Knowledge, TOOLS, grounded
from model import Model

# Acceptable evidence sets refer to physical source locations, not exact model wording.
CASES=[
 # The visitor already names all three towns. Grade the geographical/historical explanation.
 ("city","wuhan","汉口武昌汉阳为什么常被合称三镇？",["towns","overview.1.","overview.2.4"],["汉水|汉江","交汇|改由|分隔|分割|汇合","三镇|汉口"]),
 ("community","community","没做过项目的人怎么学会独立接单？",["community.4.","community.7.","community.11."],["订单"]),
 ("entity","spu","SPU的英文是什么？",["spu.5."],["Super Person Unit"]),
 ("deadline","saig","十一月二十日算点赞还是算报名？",["deadline"],["点赞","待公告|未公告|尚未公布|另行公告|待定|未公布"]),
 ("submit","saig","有作品网址还要给评委什么材料？",["register"],["简介","视频"]),
 ("food","food","汉口人说的过早是指什么？",["breakfast","book.163."],["早餐|早点|早饭"]),
 ("place","attraction","黄鹤楼现在看到的楼体是什么时期重建的？",["book.6."],["1985"]),
 ("guide","guide","想在汉口老城慢逛半天，先吃早点再看老建筑",["oldtown","book.201."],["黎黄陂路|老建筑|老街"]),
 ("sites","community","武汉的社区布局在哪两处？",["community.3."],["智民里","光谷创新天地"]),
 ("unknown","community","今天晚上八点到智民里前台，能保证免费入场吗？",[],[])
]

def run(live=False):
    k=Knowledge()
    model=Model() if live else None
    result=[]
    for name,tool,q,gold,terms in CASES:
        rows=k.search(q,TOOLS[tool],5)
        ids=[r["id"] for r in rows]
        ranks=[i for i,rid in enumerate(ids,1) if any(rid.startswith(g) for g in gold)]
        record={"case":name,"query":q,"ids":ids,"rank":min(ranks,default=None),"has_gold":bool(gold)}
        if live:
            ans=grounded(model,q,rows)
            text=ans["answer"]
            if not gold:
                ok=not ans["supported"] or ("确认" in text or "核实" in text or "无法" in text) and "保证免费入场。" not in text
            else:
                ok=bool(ans["supported"] and all(any(v.lower() in text.lower() for v in t.split("|")) for t in terms)
                        and any(any(c["id"].startswith(g) for g in gold) for c in ans["citations"]))
            record.update(answer=text,citations=ans["citations"],answer_check=ok)
        result.append(record)
    eligible=[r for r in result if r["has_gold"]]
    return {"retrieval_hits_at_5":sum(bool(r["rank"]) for r in eligible),"retrieval_total":len(eligible),
            "mrr_at_5":round(sum(1/r["rank"] if r["rank"] else 0 for r in eligible)/len(eligible),3),
            "answers_passed":sum(r.get("answer_check",False) for r in result) if live else None,
            "cases":result}

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--live",action="store_true")
    ap.add_argument("--out",type=Path)
    a=ap.parse_args()
    r=run(a.live)
    data=json.dumps(r,ensure_ascii=False,indent=2)
    if a.out: a.out.write_text(data,encoding="utf8")
    sys.stdout.reconfigure(encoding="utf8")
    print({k:v for k,v in r.items() if k!="cases"})
    for c in r["cases"]:
        print(c["case"],c["rank"],c.get("answer_check",""))
    sys.exit(int(r["retrieval_hits_at_5"]!=r["retrieval_total"] or (a.live and r["answers_passed"]!=len(r["cases"]))))
