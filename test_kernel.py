"""Offline tests for the tool-calling kernel: no network, the model is scripted."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agent import Agent
from kernel import Kernel
from kernel_tools import Toolbox, resolve, TOOL_DEFS


def call(name, args, i=0):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent = Agent(str(Path(self.tmp.name) / "s.sqlite"), model=Mock())
        self.agent.model.ask.return_value = {"id": "none", "order": []}
        self.kernel = Kernel(self.agent)

    def tearDown(self):
        self.tmp.cleanup()

    def test_aliases_resolve_to_catalogue(self):
        self.assertEqual(resolve("光谷")[0], "光谷广场")
        self.assertEqual(resolve("省博")[0], "湖北省博物馆")
        self.assertIsNone(resolve("火星基地")[0])

    def test_schema_errors_are_reported_not_raised(self):
        box = Toolbox(self.agent, {"days": {}}, [])
        self.assertFalse(box.call("plan_trip", {"days": 9})["ok"])
        self.assertFalse(box.call("no_such_tool", {})["ok"])
        self.assertFalse(box.call("edit_trip", {"day": 1, "actions": [{"type": "delay_start", "minutes": 30}]})["ok"])

    def test_plan_then_edit_keeps_stops_and_shifts_time(self):
        draft = {"days": {}}
        box = Toolbox(self.agent, draft, [])
        made = box.call("plan_trip", {"days": 1, "start": "13:00", "end": "17:30", "interests": "汉口 老建筑"})
        self.assertTrue(made["ok"], made)
        first = draft["days"]["1"]
        self.assertGreaterEqual(first["contract"]["start"], 780)
        moved = box.call("edit_trip", {"day": 1, "actions": [{"type": "delay_start", "minutes": 30}]})
        self.assertTrue(moved["ok"], moved)
        self.assertEqual(draft["days"]["1"]["order"], first["order"])
        self.assertEqual(draft["days"]["1"]["contract"]["start"], first["contract"]["start"] + 30)
        self.assertEqual(box.mode, "edit")

    def test_citations_only_for_retrieved_refs(self):
        box = Toolbox(self.agent, {"days": {}}, [])
        box.call("search_knowledge", {"query": "热干面", "topic": "food", "k": 2})
        answer, cites = Kernel.ground("热干面要快拌快吃。[S1]\n这句没有出处。[S9]", box)
        self.assertNotIn("[S", answer)
        self.assertEqual(len(cites), 1)
        self.assertEqual(cites[0]["claim"], "热干面要快拌快吃。")

    def test_loop_runs_tools_then_answers(self):
        replies = iter([
            {"role": "assistant", "content": "", "tool_calls": [call("search_knowledge", {"query": "武汉 三镇", "topic": "wuhan"})]},
            {"role": "assistant", "content": "武汉由汉口、武昌、汉阳三镇组成。[S1]"},
        ])
        self.kernel.chat = lambda *a, **k: next(replies)
        events = []
        result = self.kernel.respond("s1", "武汉三镇是哪三镇", emit=lambda kind, data: events.append(kind))
        self.assertEqual(result["answer"], "武汉由汉口、武昌、汉阳三镇组成。")
        self.assertEqual(len(result["citations"]), 1)
        self.assertIn("tool", events)

    def test_budget_exhaustion_still_answers(self):
        loop = {"role": "assistant", "content": "", "tool_calls": [call("get_trip", {})]}
        replies = iter([loop] * 6 + [{"role": "assistant", "content": "目前还没有行程，告诉我你玩几天？"}])
        self.kernel.chat = lambda *a, **k: next(replies)
        result = self.kernel.respond("s2", "我的行程呢")
        self.assertIn("几天", result["answer"])

    def test_tool_definitions_are_well_formed(self):
        names = {t["function"]["name"] for t in TOOL_DEFS}
        self.assertTrue({"search_knowledge", "plan_trip", "edit_trip", "find_place", "remember"} <= names)


if __name__ == "__main__":
    unittest.main()


class GroundingGuardTests(KernelTests):
    def test_ungrounded_long_answer_is_sent_back_once(self):
        long_guess = "SPU 是超级生产者单元，" + "这是凭记忆写的一大段说明，" * 8
        replies = iter([
            {"role": "assistant", "content": long_guess},
            {"role": "assistant", "content": "", "tool_calls": [call("search_knowledge", {"query": "SPU 超级个体单元", "topic": "spu"})]},
            {"role": "assistant", "content": "SPU 是超级个体单元。[S1]"},
        ])
        self.kernel.chat = lambda *a, **k: next(replies)
        result = self.kernel.respond("g1", "SPU 是什么")
        self.assertEqual(result["answer"], "SPU 是超级个体单元。")
        self.assertTrue(any(t.get("step") == "grounding_retry" for t in result["trace"]))

    def test_short_greeting_is_not_blocked(self):
        self.kernel.chat = lambda *a, **k: {"role": "assistant", "content": "你好呀！想先聊武汉还是排行程？"}
        self.assertIn("你好", self.kernel.respond("g2", "你好")["answer"])
