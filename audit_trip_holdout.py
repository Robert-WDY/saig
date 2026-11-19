"""First-use acceptance inputs for overnight handoff, transit directions and unpriced travel."""
import json
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import requests

QUESTIONS={
 "hotel":"住在江汉路附近，两天都以江汉路作住宿锚点。第一天想看黄鹤楼，晚上回住处。次日要从住处出发逛黎黄陂路。",
 "rail":"从黄鹤楼集合，只到汉口江滩玩一站，转场只接受地铁。给我上车和下车的站名。",
 "unknown_price":"我们四个人在户部巷会合，只坐打表出租车去湖北省博物馆。车费全团必须保证在80元以内，没有固定报价。请排这个行程。"}
def run(case,out):
    q=QUESTIONS[case]
    s=requests.Session();s.trust_env=False
    r=s.post("http://127.0.0.1:18943/chat",json={"query":q,"session":"independent-"+uuid4().hex},timeout=600)
    r.raise_for_status();v=r.json();days=v["days"]
    try:
        if case=="hotel":
            a,b=days["1"],days["2"]
            ok=(a["contract"]["destination"]==b["contract"]["origin"]=="江汉路" and "黄鹤楼" in a["order"] and "黎黄陂路" in b["order"]
                and any(t.get("audit",{}).get("overnights",[{}])[0].get("status")=="同一锚点" for t in v["trace"] if t.get("step")=="trip_review"))
        elif case=="rail":
            legs=days["1"]["audit"]["legs"]
            ok=days["1"]["order"]==["汉口江滩"] and any(l["mode"]=="metro" and l["origin"]=="黄鹤楼" and l["destination"]=="汉口江滩" and "司门口黄鹤楼" in l["directions"] and "黄浦路" in l["directions"] for l in legs)
        else:
            ok=not days and v["mode"]=="clarify" and any(term in v["answer"] for term in ("车费","预算","价格","报价"))
    except (KeyError,IndexError):ok=False
    (out/(case+".json")).write_text(json.dumps({"query":q,"accepted":ok,"response":v},ensure_ascii=False,indent=2),"utf8")
    print(case,ok,v["answer"][:140],flush=True);return ok

if __name__=="__main__":
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results=list(executor.map(lambda c:run(c,out),QUESTIONS))
    raise SystemExit(not all(results))

