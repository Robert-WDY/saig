"""Independent, offline probes for retrieval and structured edit semantics (no model calls)."""
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Agent
from kernel_tools import Toolbox
from route_edits import edit_route


RETRIEVAL = [
    ("报名交什么，项目网址可以不交吗", "saig", "register"),
    ("人气榜点赞和提交作品是同一个截止时间吗", "saig", "deadline"),
    ("社区怎么把企业的真实订单交给开发者做", "community", "community.4.1"),
    ("新人怎么跟着有经验的人学真实项目", "community", "community.7.1"),
    ("SPU对交付结果担什么责任，出错后如何改进", "spu", "spu.11.1"),
    ("湖北省博物馆的越王勾践剑，最晚几点停止入场", "attraction", "book.16.1"),
]


def run(folder):
    output = {}
    with tempfile.TemporaryDirectory() as temp:
        model = Mock()
        model.ask.return_value = {"id": "none", "order": []}
        agent = Agent(str(Path(temp) / "test.sqlite"), model=model)
        retrieval = []
        for query, topic, wanted in RETRIEVAL:
            hits = agent.kb.search(query, [topic], 5)
            ids = [row["id"] for row in hits]
            retrieval.append({"query": query, "topic": topic, "expected": wanted, "found": ids,
                              "rank": ids.index(wanted) + 1 if wanted in ids else None})
        output["retrieval"] = retrieval

        first = edit_route(agent.store, "synthetic", "create", {
            "plan": "new", "day": "1", "add": ["黎黄陂路", "巴公房子", "江汉关"], "remove": []})
        second = edit_route(agent.store, "synthetic_other", "create", {
            "plan": "new", "day": "1", "add": ["古琴台"], "remove": []})
        draft = {"days": {"1": first["cards"]["1"], "2": second["cards"]["1"]}}
        box = Toolbox(agent, draft, [])
        before = deepcopy(draft)
        actions = [{"type": "move_to_day", "place": "黎黄陂路", "to_day": 2}, {"type": "set_start", "time": "10:00"}]
        together = box.call("edit_trip", {"day": 1, "actions": actions})
        isolated = Toolbox(agent, deepcopy(before), [])
        separate = [isolated.call("edit_trip", {"day": 1, "actions": [action]}) for action in actions]
        output["compound"] = {"actions": actions, "accepted": together["ok"],
                              "source_start": draft["days"]["1"]["contract"]["start"],
                              "moved": "黎黄陂路" in draft["days"]["2"]["order"] and "黎黄陂路" not in draft["days"]["1"]["order"],
                              "separate_accepted": [r["ok"] for r in separate],
                              "separate_start": isolated.draft["days"]["1"]["contract"]["start"]}
        view = box.call("get_trip", {})
        output["readback"] = {"returned_day_fields": sorted(view["days"]["1"]),
                              "stored_leg_fields": sorted(draft["days"]["1"]["audit"]["legs"][0])}

    checks = {
        "ranked_source_in_top_five": all(r["rank"] is not None for r in output["retrieval"]),
        "compound_matches_feasible_sequential_actions": (
            all(output["compound"]["separate_accepted"]) and output["compound"]["accepted"]
            and output["compound"]["moved"] and output["compound"]["source_start"] == output["compound"]["separate_start"] == 600),
    }
    output["checks"] = checks
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "module-checks.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf8")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1])))
