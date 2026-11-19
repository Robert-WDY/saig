"""Sealed transfer tasks. Do not use these turns as new prompt examples or tune their expected output."""
import json
import argparse
from pathlib import Path
import time
import tempfile
from agent import Agent,memory_view,CHECK
from audit_visitors import fixture
from semantics import interpret

def run(out):
    rows=[]
    def record(id,q,expect,fn):
        start=time.monotonic()
        try: passed,actual=fn()
        except Exception as e: passed,actual=False,repr(e)
        rows.append({"id":id,"input":q,"expected":expect,"passed":bool(passed),"actual":actual,
                     "seconds":round(time.monotonic()-start,2)})
        out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
    with tempfile.TemporaryDirectory() as tmp:
        a=Agent(str(Path(tmp)/"run.db"))
        # Isolated model semantics: inspect the patch, before execution can accidentally hide an error.
        for id,q,expect,judge in [
         ("relative_reference","把第一天最后一站的参观时间定成三刻钟，其他照旧。","仅第1天智民里的时长45分钟",
          lambda s:s["mode"]=="edit" and len(s["days"])==1 and s["days"][0]["day"]==1 and s["days"][0]["set"]=={"durations":{"智民里":45}}),
         ("preserve_origin","第二天继续从户部巷集合，但别把它算作游览项目，只去昙华林就行。","删除/排除户部巷游览，保留起点，明确必去昙华林",
          lambda s:s["mode"]=="edit" and len(s["days"])==1 and s["days"][0]["day"]==2 and
            "户部巷" in s["days"][0].get("exclude",[])+s["days"][0].get("remove",[]) and
            s["days"][0].get("set",{}).get("origin","户部巷")=="户部巷"),
         ("unknown_station","我要去武汉站坐车，之前那个汉口站千万别用。硬条件是下午四点武汉站发车。","未覆盖车站须指出，不能代换成汉口站",
          lambda s:(s["mode"]=="clarify" or bool(s.get("unsupported"))) and
            not any(o.get("set",{}).get("destination")=="汉口站" for o in s.get("days",[]))),
         ("recall_without_write","上次提过的地点里，第一天最后一站是哪里？别改。","读取既有对象，不生成编辑也不写人物记忆",
          lambda s:s["mode"]=="info" and not s["days"] and not s["facts"]),
        ]:
            def check(q=q,judge=judge):
                result=a.understand(q,fixture())
                return judge(result),result
            record(id,q,expect,check)
        # Unseeded, previously unseen customer. Every dependent turn must find the original live card.
        session="new-family"
        q="我带孩子在武昌玩，约了上午十一点在户部巷碰头，想逛户部巷和昙华林，两处都想去。下午四点结束，帮我排。"
        def start():
            r=a.respond(session,q)
            c=r["days"].get("1",{});contract=c.get("contract",{})
            ok=r["mode"]=="plan" and contract.get("origin")=="户部巷" and contract.get("start")==660 and contract.get("end")==960 and {"户部巷","昙华林"}<=set(c["order"])
            return ok,r
        record("family_start",q,"从冷启动生成满足双地点和时间的武昌卡",start)
        original=rows[-1]["actual"].get("days",{}) if isinstance(rows[-1]["actual"],dict) else {}
        q="有点失望。"
        def complain():
            r=a.respond(session,q)
            return bool(original) and r["mode"]=="clarify" and r["days"]==original and bool(r["answer"].strip()),r
        record("family_vague",q,"上一步已成功才可验：先询问原因，完整保留原卡",complain)
        q="时间不用改。我不喜欢走马观花，昙华林给孩子留一个小时看建筑，其余都沿用。"
        def repair():
            r=a.respond(session,q);c=r["days"].get("1",{})
            prior=original.get("1",{})
            target={**prior.get("contract",{}),"durations":{**prior.get("contract",{}).get("durations",{}),"昙华林":60}}
            return bool(original) and r["mode"]=="edit" and c["contract"]==target and c["order"]==prior["order"],r
        record("family_resolve",q,"家长说明原因后，仅改孩子要停留的地点，约定和其他站序保留",repair)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True)
    run(p.parse_args().out)
