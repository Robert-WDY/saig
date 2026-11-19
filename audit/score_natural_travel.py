"""Compare two-turn outcomes, logical calls and separately measured provider attempts."""
from pathlib import Path
from statistics import median
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from knowledge import Knowledge

def score(folder):
    docs=Knowledge().by_id
    rows=[]
    for case in ("afternoon","pickup","community","oldtown"):
        path=folder/(case+"-1.json")
        archive=json.loads(path.read_text("utf8"))
        turns=archive["turns"]
        assert len(turns)==2 and "replay" in archive
        first=turns[0]["result"]
        for i,t in enumerate(turns):
            r=t["result"];a=r["answer"]
            card=(r["preview"] or r["days"]).get("1",{})
            c=card.get("contract",{})
            citations=r["citations"]
            checks={"response":t["http"]==200,"sources":all(x["id"] in docs and x["quote"] in docs[x["id"]]["text"]
                      and x["claim"] in a and x["source"]==docs[x["id"]]["source"] for x in citations)}
            if case=="afternoon":
                checks.update(start=c.get("origin")=="户部巷" and c.get("start")==[900,930][i],
                              deadline=c.get("end")==1020 and card.get("audit",{}).get("arrival",1500)<=1020,
                              stops=card.get("order")==["黄鹤楼"],version=(r["mode"]=="plan" if i==0 else
                              r["mode"]=="preview" and first["days"]==r["days"]))
            elif case=="pickup":
                checks.update(start=c.get("origin")=="江汉路" and c.get("start")==540, destination=c.get("destination")=="汉口站",
                        deadline=c.get("end")==[840,870][i] and c.get("buffer")==20 and card["audit"]["arrival"]<=c["end"]-20,
                        visits="黎黄陂路" in card.get("order",[]) and (not i or card["order"]==first["days"].get("1",{}).get("order")),
                        version=r["mode"]==["plan","edit"][i] and r["preview"] is None)
            elif case=="community":
                if i==0:
                    checks.update(location="智民里" in a,teaching=any(w in a for w in ("订单","带教","实战")) and
                                  any(x["id"]=="community.7.1" for x in citations))
                else:
                    checks.update(opening=any(w in a for w in ("确认","核实","未公布","未列","未给","未说明")) and
                                  not any(w in a for w in ("闭馆时间","肯定能","保证能")))
            else:
                checks.update(memory=any(f["subject"]=="self" and f["relation"]=="likes" and f["object"]=="老建筑" for f in r["facts"]),
                              advice=bool(citations))
                if i:
                    # Extract actual candidate names from the previous response's cited text, not the next response's search terms.
                    import re
                    names=set()
                    for phrase in re.findall(r"[\u3400-\u9fff]{2,}(?:路|街|巷|里)",first["answer"]):
                        names.update(phrase[-n:] for n in range(3,min(7,len(phrase))+1))
                    names.update(n for step in first["trace"] if step.get("step")=="offered_places" for n in step["names"])
                    checks.update(prior_choice=any(n not in turns[0]["request"]["query"] and n in first["answer"] and n in a
                                                   and any(n in x["quote"] for x in citations) for n in names),
                                  read_only=r["facts"]==first["facts"])
            events=r["events"];requests=[e for e in events if e["stage"]=="model_http"]
            rows.append({"case":case,"turn":i+1,"passed":all(checks.values()),"checks":checks,"logical_calls":sum(e["stage"]=="model" for e in events),
                         "provider_calls":len(requests) if requests else None,"retries":sum(e["attempt"]>1 for e in requests) if requests else None,
                         "wall_s":t["wall_s"]})
    out={"passes":sum(x["passed"] for x in rows),"median_calls":median(x["logical_calls"] for x in rows),
         "median_wall_s":median(x["wall_s"] for x in rows),"rows":rows}
    (folder/"score.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),"utf8")
    print(folder,out["passes"],out["median_calls"],out["median_wall_s"],[(x["case"],x["turn"],[k for k,v in x["checks"].items() if not v]) for x in rows if not x["passed"]])
if __name__=="__main__":
    for arg in sys.argv[1:]:score(Path(arg))
