"""Retain original sealed assertions and guard against an unrelated clock matching a duration."""
import json
from pathlib import Path
import re
import sys

def review(path):
    rows=json.loads(path.read_text(encoding="utf8"))
    result={r["case"]:r["passed"] for r in rows}
    if "讨论之后读回修改" in result:
        edit,read=rows[0]["result"],rows[1]["result"]
        stored=edit.get("days",{}).get("2",{}).get("contract",{}).get("durations",{})
        answer=read.get("answer","")
        amount=re.search(r"(?:停留|游览|留了|留出|安排).*?(30\s*分钟|三十分钟|半小时)",answer)
        result["读回的是已提交的停留时长"]=rows[0]["passed"] and stored.get("户部巷")==30 and bool(amount)
        result["插入咨询后仍采用原预览"]=all(result.get(n,False) for n in ("预览后插入知识问答","预览间隙咨询","跨话题采纳试排"))
    if "负向约束读回" in result:
        recalled=rows[0]["result"]
        refs=[ref for t in recalled.get("trace",[]) if t.get("step")=="session_read" for ref in t["records"]]
        answer=recalled.get("answer","")
        result["只返回第二天被问的必去条件"]=refs==["day/2/must"] and "第1天" not in answer and "没有可确认" not in answer
    path.with_name(path.stem+"-strict.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
    return all(result.values())
if __name__=="__main__":
    sys.exit(not review(Path(sys.argv[1])))
