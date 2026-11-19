"""Independent evidence challenges: multi-document completeness, wrong-domain decoy, partial knowledge, contradiction."""
import argparse
import json
from pathlib import Path
from knowledge import Knowledge,TOOLS,grounded
from model import Model

def run(out):
    kb=Knowledge();model=Model();rows=[]
    def probe(id,q,docs,needed,judge):
        ids=[d["id"] for d in docs]
        try:
            ans=grounded(model,q,docs)
            cites=ans["citations"]
            anchored=all(c["id"] in ids and c["quote"] in next(d for d in docs if d["id"]==c["id"])["text"] and c["claim"] in ans["answer"] for c in cites)
            support={c["id"] for c in cites}
            find=all(n in ids for n in needed)
            ok=find and set(needed)<=support and anchored and judge(ans)
        except Exception as e:
            ans={"error":repr(e)};find=all(n in ids for n in needed);ok=False
        rows.append({"id":id,"input":q,"context":ids,"required_sources":needed,"retrieved_all":find,
                     "passed":bool(ok),"answer":ans})
        out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
    q="假如我的视频没进人气榜前十八，仍能通过赛区入选吗？报名表的视频能用作品体验页顶替吗？"
    probe("independent_two_documents",q,kb.search(q,TOOLS["saig"],5),["selection","register"],
          lambda a:all(w in a["answer"] for w in ("赛区","视频")) and any(x in a["answer"] for x in ("必填","必须","不能","不可","必交")))
    q="有朋友说社区的线下讲座每周二下午两点开。我可以按这个时间去吗？"
    probe("near_match_has_no_schedule",q,[kb.by_id["community.7.1"],kb.by_id["community.6.1"]],[],
          lambda a:not a["supported"] and not a["citations"])
    q="从哪个地铁站去智民里比较方便？还能确认今晚八点一定能进去吗？"
    probe("partial_answer_with_limit",q,kb.search(q,TOOLS["community"],5),["venue"],
          lambda a:any(w in a["answer"] for w in ("大智路","江汉路")) and any(w in a["answer"] for w in ("无法","核实","确认","咨询")))
    q="武汉三镇是不是指汉口、襄阳、武昌？请纠正我填错的名字。"
    probe("correct_false_premise",q,kb.search(q,TOOLS["wuhan"],5),["towns"],
          lambda a:all(w in a["answer"] for w in ("汉阳","汉口","武昌")) and "襄阳是武汉三镇之一" not in a["answer"])
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True)
    run(p.parse_args().out)
