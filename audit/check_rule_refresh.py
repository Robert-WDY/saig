"""Exercise an isolated rules update using two new visitors and the configured model."""
import json
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Agent
from knowledge import DATA
from limits import turn_budget
from serve import ReviewedSources


def run():
    rows=json.loads((DATA/"official.json").read_text("utf8"))
    output=[]
    with tempfile.TemporaryDirectory() as root:
        path=Path(root)/"official.json"
        agent=Agent(str(Path(root)/"test.sqlite"))
        registry=ReviewedSources(agent,path)
        for fixture in (False,True):
            if fixture:
                row=next(r for r in rows if r["id"]=="deadline")
                row.update(edition="隔离测试新公告",text="模拟公告规定报名于 11 月 25 日 18:00 截止。人气榜点赞统计仍于 11 月 20 日 23:59:59 北京时间截止。")
            path.write_text(json.dumps(rows,ensure_ascii=False),encoding="utf8")
            sid=uuid4().hex
            with turn_budget(lambda:agent.store.charge(sid,24,48)):
                result=registry.current().respond(sid,"我想11月21日才报名，到时还能报名吗？那天视频收到的赞还算人气榜吗？")
            output.append({"fixture":fixture,"answer":result["answer"],"sources":[[r["id"],r["edition"]] for r in result["citations"]],
                           "jobs":[t["query"] for t in result["trace"] if "tool" in t and "query" in t]})
    return output


if __name__=="__main__":
    results=run()
    print(json.dumps(results,ensure_ascii=False,indent=2))
    assert all(any(i=="deadline" for i,_ in r["sources"]) and "20" in r["answer"] for r in results)
    assert "25" in results[1]["answer"] and any(edition=="隔离测试新公告" for _,edition in results[1]["sources"])
