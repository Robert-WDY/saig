"""Fixed independent visitor conversations through the running HTTP API."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4
import requests

ROOT=Path(__file__).resolve().parents[1]
TZ=timezone(timedelta(hours=8))
CASES={
    "metro":[
        "{date}上午九点我们两个人在黄鹤楼集合。只游湖北省博物馆这一站，只坐地铁，十一点四十五前要结束。请把换乘和走路距离也写出来。",
        "朋友的膝盖不舒服，景点之间这段转场步行最多500米，其他条件不变。只试排，看能不能做到，先别改正式行程。",
        "那就先看原来那张卡。我们要在哪一站换乘，预计几点到湖北省博物馆？"],
    "community":[
        "我第一次去武汉，想带做设计的同学去江岸的数命SPU社区看看。具体在哪儿？没接过项目的人，在那儿怎么学会独立接单？",
        "所以你刚说的江岸会场一处就有近八千平方米吗？还是和另一个地方合起来的？另一处叫什么？",
        "我想明晚八点过去，能保证免费进场吗？那晚前台是谁值班？请把能确定和暂时查不到的说清楚。"],
    "family_event":[
        "帮我记一下，我叫林川，妈妈叫晓岚，她喜欢老建筑。另外，参加SAIG线上赛的接待员需要展示哪四项功能？",
        "我要填表：我叫什么、她叫什么？有项目主页的话，还要交演示视频吗？",
        "我刚才把她的名字写错了，应该是晓兰，喜好照旧。还有，报名收费吗？",
        "最后帮我核对一下妈妈现在的姓名和喜好，不要改记录。"],
    "edit":[
        "我们玩两天。第一天从江汉路出门，必须逛黎黄陂路；第二天从户部巷出门，一定去黄鹤楼。两天都九点出发，每天最多两个游览点。",
        "第一天不动。第二天如果十点才从户部巷出发呢？只展示备选，暂时别替我决定。",
        "我们决定采用刚才十点出发的那个版本。",
        "票买好了：第二天下午四点从汉口站坐车走，要提前四十分钟进站。黄鹤楼还要去，第一天照旧。"]}

def write(path,data):
    stage=path.with_suffix(".tmp")
    stage.write_text(json.dumps(data,ensure_ascii=False,indent=2),"utf8")
    stage.replace(path)

def send(session,base,body):
    start=perf_counter()
    at=datetime.now(TZ).isoformat()
    try:
        with session.post(base+"/chat",json=body,timeout=(5,360),stream=True) as res:
            headers=perf_counter()
            payload=res.json()
            return {"at":at,"http":res.status_code,"headers_s":round(headers-start,3),
                    "wall_s":round(perf_counter()-start,3),"result":payload}
    except (ValueError,requests.RequestException) as exc:
        return {"at":at,"http":None,"error":type(exc).__name__,"wall_s":round(perf_counter()-start,3),"result":{}}

def run(case,out,base,repeats,inputs):
    with requests.Session() as session:
        session.trust_env=False
        for attempt in range(1,repeats+1):
            sid="tourist-"+uuid4().hex
            turns=[]
            archive={"case":case,"attempt":attempt,"session":sid,"turns":turns}
            path=out/f"{case}-{attempt}.json"
            for question in inputs[case]:
                req={"session":sid,"query":question,"request_id":uuid4().hex,"diagnostics":True}
                turn=send(session,base,req)
                turns.append({"request":req,**turn})
                write(path,archive)
            archive["replay"]=send(session,base,turns[-1]["request"])
            write(path,archive)
            print(case,attempt,[t["http"] for t in turns],flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--base",default="http://127.0.0.1:18943")
    p.add_argument("--repeats",type=int,default=3)
    args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    date=(datetime.now(TZ).date()+timedelta(days=1)).strftime("%Y年%m月%d日")
    inputs={k:[q.format(date=date) for q in qs] for k,qs in CASES.items()}
    files=[*ROOT.glob("*.py"),*ROOT.joinpath("data").glob("*.jsonl"),
           *(p for p in (ROOT/"data").glob("*.json") if not p.name.startswith("eval-")),Path(__file__)]
    write(args.out/"manifest.json",{"started":datetime.now(TZ).isoformat(),"inputs":inputs,
          "repeats":args.repeats,"workers":len(CASES),"base":args.base,
          "sha256":{f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in files}})
    with ThreadPoolExecutor(max_workers=len(CASES)) as pool:
        list(pool.map(lambda case:run(case,args.out,args.base,args.repeats,inputs),CASES))
