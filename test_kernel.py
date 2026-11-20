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


class DegradedTests(KernelTests):
    def test_provider_failure_answers_from_official_passages(self):
        from model import ModelError
        self.kernel.chat = Mock(side_effect=ModelError("down"))
        result = self.kernel.respond("d" * 32, "数命 SPU 社区在哪里？")
        self.assertEqual(result["mode"], "degraded")
        self.assertTrue(result["citations"])
        self.assertIn("模型服务暂时繁忙", result["answer"])


class PublicTrialTests(unittest.TestCase):
    def test_visitor_limiter_burst_and_daily(self):
        from serve import VisitorLimiter
        limiter = VisitorLimiter(per_minute=2, per_day=3)
        self.assertIsNone(limiter.allow("a"))
        self.assertIsNone(limiter.allow("a"))
        self.assertIn("太快", limiter.allow("a"))
        self.assertIsNone(limiter.allow("b"))
        limiter.recent["a"] = []
        self.assertIsNone(limiter.allow("a"))
        limiter.recent["a"] = []
        self.assertIn("用完", limiter.allow("a"))

    def test_public_mode_needs_no_invite_but_hides_debug_and_limits(self):
        import threading
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch
        import requests
        from serve import VisitorLimiter, handler
        from storage import Sessions
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        agent = Mock()
        agent.store = Sessions(str(Path(tmp.name) / "s.sqlite"))
        agent.kb.rows = []
        agent.model.name = "test"
        agent.respond.side_effect = lambda sid, q, req: agent.store.save(sid, req, q, 0, {}, {"answer": "ok", "trace": [{"tool": "wuhan", "query": "q"}], "facts": ["x"]})
        api = handler(agent, {"test.local"}, "", 50, 50, True, VisitorLimiter(per_minute=2, per_day=10))
        api.log_message = lambda *a: None
        server = ThreadingHTTPServer(("127.0.0.1", 0), api)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        http = requests.Session()
        http.trust_env = False
        self.addCleanup(http.close)
        headers = {"Host": "test.local"}
        with patch.dict("os.environ", {"SAIG_KERNEL": "v1"}):
            first = http.post(base + "/chat", json={"session": "1" * 32, "query": "q", "request_id": "r1"}, headers=headers, timeout=3)
            self.assertEqual(first.status_code, 200)
            self.assertNotIn("trace", first.json())
            self.assertEqual(http.post(base + "/tool", json={"session": "1" * 32, "query": "q"}, headers=headers, timeout=3).status_code, 404)
            http.post(base + "/chat", json={"session": "1" * 32, "query": "q2", "request_id": "r2"}, headers=headers, timeout=3)
            limited = http.post(base + "/chat", json={"session": "1" * 32, "query": "q3", "request_id": "r3"}, headers=headers, timeout=3)
            self.assertEqual(limited.status_code, 429)
            self.assertIn("太快", limited.json()["error"])


class VisitorToolsTests(KernelTests):
    def test_arrival_guide_routes_gateways_and_rejects_unknown(self):
        box = Toolbox(self.agent, {"days": {}}, [])
        r = box.call("arrival_guide", {"gateway": "天河机场"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["get_off"], "江汉路站")
        self.assertEqual(r["transfers"], 0)
        r = box.call("arrival_guide", {"gateway": "汉口站", "destination": "黄鹤楼"})
        self.assertEqual(r["metro_steps"][0], "汉口火车站上2号线")
        self.assertFalse(box.call("arrival_guide", {"gateway": "天河机场", "destination": "火星"})["ok"])
        self.assertFalse(box.call("arrival_guide", {"gateway": "光谷"})["ok"])

    def test_weather_failure_is_reported_not_invented(self):
        from unittest.mock import patch
        box = Toolbox(self.agent, {"days": {}}, [])
        with patch("kernel_tools.forecast", return_value=None):
            self.assertFalse(box.call("get_weather", {})["ok"])
        fake = {"now": {"temp_c": 9.0}, "days": [{"date": "2026-11-21", "weather": "小雨"}] * 5, "source": "test"}
        with patch("kernel_tools.forecast", return_value=fake):
            r = box.call("get_weather", {"days": 2})
        self.assertEqual(len(r["days"]), 2)


class MoveStopTests(KernelTests):
    def test_move_stop_to_afternoon_keeps_every_other_stop(self):
        draft = {"days": {}}
        box = Toolbox(self.agent, draft, [])
        must = [{"place": p} for p in ["古琴台", "龟山公园", "黄鹤楼", "武汉长江大桥", "户部巷"]]
        self.assertTrue(box.call("plan_trip", {"days": 1, "must": must})["ok"])
        before = list(draft["days"]["1"]["order"])
        r = box.call("edit_trip", {"day": 1, "actions": [{"type": "move_stop", "place": "黄鹤楼", "period": "afternoon"}]})
        self.assertTrue(r["ok"], r)
        stops = {s["place"]: s["start"] for s in draft["days"]["1"]["audit"]["stops"]}
        self.assertGreaterEqual(stops["黄鹤楼"], 13 * 60)
        self.assertEqual(sorted(stops), sorted(before))
        self.assertEqual(draft["days"]["1"]["contract"]["start"], 9 * 60)

    def test_remove_and_readd_same_place_is_not_a_conflict(self):
        draft = {"days": {}}
        box = Toolbox(self.agent, draft, [])
        box.call("plan_trip", {"days": 1, "must": [{"place": "黄鹤楼"}, {"place": "户部巷"}]})
        r = box.call("edit_trip", {"day": 1, "actions": [{"type": "remove_stop", "place": "黄鹤楼"}, {"type": "add_stop", "place": "黄鹤楼"}]})
        self.assertTrue(r["ok"], r)


class ReorderTests(unittest.TestCase):
    def test_reorder_prefers_less_travel_over_filling_the_wait(self):
        from planning import new_contract, reorder
        c = new_contract()
        c["windows"] = {"黄鹤楼": [780, 1439]}
        order, proof = reorder(c, ["古琴台", "龟山公园", "武汉长江大桥", "黄鹤楼", "户部巷"])
        self.assertEqual(order, ["古琴台", "龟山公园", "武汉长江大桥", "户部巷", "黄鹤楼"])
        self.assertFalse(proof["violations"])
