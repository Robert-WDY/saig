"""Regression checks on saved visitor cards, independent of model phrasing."""
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from agent import Agent
from kernel_tools import Toolbox
from kernel import Kernel
from route_edits import edit_route
from planning import Invalid, evaluate, new_contract, solve
from places import ATLAS_POINTS, GATEWAYS
from transport import choose


class VisitorRepairTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.agent = Agent(str(Path(folder.name) / "routes.db"), model=Mock())
        self.agent.model.ask.return_value = {"id": "none", "order": []}
        self.cards = {}
        for day, stops in enumerate((["巴公房子", "黎黄陂路", "江汉关"], ["古琴台"]), 1):
            r = edit_route(self.agent.store, str(day), "map", {"plan": "new", "day": "1", "add": stops, "remove": []})
            self.cards[str(day)] = r["cards"]["1"]
        self.box = Toolbox(self.agent, {"days": deepcopy(self.cards)}, [])

    def edit(self, actions, **extra):
        return self.box.call("edit_trip", {"day": 1, "actions": actions, **extra})

    def test_multi_day_preview_view_and_adoption(self):
        actions = [{"type": "move_to_day", "place": "巴公房子", "to_day": 2},
                   {"type": "set_start", "time": "10:10"}, {"type": "set_end", "day": 2, "time": "19:10"}]
        self.assertTrue(self.edit(actions, preview=True)["ok"])
        self.assertEqual(self.box.draft["days"], self.cards)
        proposed = deepcopy(self.box.preview)
        self.assertEqual(proposed["1"]["contract"]["start"], 610)
        self.assertEqual(proposed["2"]["contract"]["end"], 1150)
        self.assertIn("巴公房子", proposed["2"]["order"])
        self.assertNotIn("巴公房子", proposed["1"]["order"])
        self.assertTrue(self.box.resolve_preview("view")["ok"])
        self.assertEqual(self.box.draft["days"], self.cards)
        self.assertTrue(self.box.resolve_preview("adopt")["ok"])
        self.assertEqual(self.box.draft["days"], proposed)
        self.assertEqual(self.box.draft["past_days"], [self.cards])
        self.assertNotIn("pending_days", self.box.draft)

    def test_failed_batch_rolls_back_earlier_changes_including_history(self):
        before = deepcopy(self.box.draft)
        r = self.edit([{"type": "set_end", "time": "20:00"},
                       {"type": "move_to_day", "place": "黄鹤楼", "to_day": 2}])
        self.assertFalse(r["ok"])
        self.assertEqual(self.box.draft, before)

    def test_unbound_clock_cannot_silently_disappear(self):
        self.box.utterance = "出门想晚一点，第一天十点出发，第二天可以逛到晚上八点。"
        before = deepcopy(self.box.draft)
        first = {"type": "set_start", "time": "10:00"}
        reply = self.edit([first])
        self.assertTrue(reply["needs_binding"])
        self.assertEqual(self.box.draft, before)
        result = self.edit([first, {"day": 2, "type": "set_end", "time": "20:00"}])
        self.assertTrue(result["ok"])
        self.assertIn("最晚 20:00", result["summary_lines"][-1])
        self.assertIn("结束游览", result["summary_lines"][-1])
        self.box.utterance = "原来十点出发的那天改到十一点。"
        self.assertTrue(self.edit([{"type": "set_start", "time": "11:00"}], reference_times=["原来十点出发"])["ok"])

    def test_stale_preview_cannot_replace_newer_map_card(self):
        self.assertTrue(self.edit([{"type": "set_start", "time": "10:00"}], preview=True)["ok"])
        self.box.draft["days"]["2"]["contract"]["end"] -= 30
        self.assertFalse(self.box.call("resolve_preview", {"action": "adopt"})["ok"])
        self.assertEqual(self.box.draft["days"]["1"], self.cards["1"])

    def test_walk_cap_proof_on_old_card(self):
        card = self.box.draft["days"]["1"]
        card["audit"]["legs"] = [
            {"mode": "walk", "walk_m": 500}, {"mode": "walk", "walk_m": 501},
            {"mode": "walk", "walk_m": 300, "estimated": True}, {"mode": "taxi", "walk_m": None}]
        frozen = deepcopy(self.box.draft)
        r = self.box.get_trip(day=1, max_walk_m=500, allowed_modes=["walk"])
        records = r["days"]["1"]["legs"]
        self.assertEqual([s["walk_check"] for s in records], ["符合", "超限", "无法验证", "无法验证"])
        self.assertEqual(records[-1]["mode_check"], "不符合")
        self.assertEqual(self.box.draft, frozen)
        del card["audit"]["legs"]
        self.assertFalse(self.box.get_trip(day=1)["days"]["1"]["has_leg_record"])

    def test_new_day_exception_does_not_erase_trip_defaults(self):
        self.box.draft["days"].pop("2")
        self.box.draft["trip_defaults"] = {"scoped": True, "avoid": ["湖北省博物馆","黄鹤楼"]}
        self.box.utterance = "明天上午想去省博。"
        self.assertTrue(self.box.append_day(2, must=["湖北省博物馆"])["ok"])
        second = self.box.draft["days"]["2"]
        self.assertIn("湖北省博物馆", second["order"])
        self.assertIn("黄鹤楼", second["contract"]["exclude"])
        self.assertIn("湖北省博物馆", self.box.draft["trip_defaults"]["avoid"])
        self.assertEqual(self.box.draft["days"]["1"], self.cards["1"])

    def test_deferred_category_is_available_even_without_naming_a_place(self):
        box = Toolbox(self.agent, {}, [], utterance="这一天先不逛展馆。")
        result = box.call("plan_trip", {"days": 1, "exclusions": [{"scope": "planned_days", "topics": ["展馆文博"]}]})
        self.assertTrue(result["ok"], result)
        original = deepcopy(box.draft["days"]["1"])
        self.assertIn("湖北省博物馆", original["contract"]["exclude"])
        box.utterance = "还富余一天，可以再排点其他的。"
        self.assertTrue(box.call("append_day", {"day": 2, "carry_exclusions": []})["ok"])
        self.assertNotIn("湖北省博物馆", box.draft["days"]["2"]["contract"]["exclude"])
        self.assertEqual(original, box.draft["days"]["1"])

    def test_repeated_option_tool_uses_original_request_once(self):
        kernel = Kernel(self.agent)
        q = "一份一天的，一份两天的，比较一下。"
        state = {"days": {}, "facts": [], "turns": []}
        self.agent.execute_turn = Mock(return_value=(deepcopy(state), {
            "deliverables": [{"status": "passed"}], "answer": "两份行程已比较。", "mode": "compose"}))
        from test_kernel import call
        kernel.chat = Mock(side_effect=[
            {"role": "assistant", "content": "", "tool_calls": [call("multi_plan", {"request": "游客一定要去武大"}, i)]}
            for i in range(2)] + [{"role": "assistant", "content": "两份行程已比较。"}])
        kernel.turn(q, state, lambda *_: None)
        self.agent.execute_turn.assert_called_once()
        self.assertEqual(self.agent.execute_turn.call_args.args[0], q)

    def test_nine_stop_transfer_proposes_a_verified_deadline(self):
        from re import search
        old = ["古琴台","龟山公园","武汉长江大桥","黄鹤楼","斗级营","户部巷","粮道街","武昌江滩"]
        wanted = old + ["黎黄陂路"]
        contract = {**new_contract(), "origin": "汉口站", "must": ["古琴台","黎黄陂路"]}
        with self.assertRaises(Invalid) as failure:
            solve(contract, old, [], add=wanted, reoptimize=True)
        match = search(r"(\d\d):(\d\d)", str(failure.exception))
        self.assertIsNotNone(match)
        cutoff = int(match[1]) * 60 + int(match[2])
        self.assertGreater(cutoff, contract["end"])
        self.assertLess(cutoff, contract["end"] + 20)
        confirmed = {**contract, "end": cutoff}
        order, proof = solve(confirmed, old, [], add=wanted, reoptimize=True)
        self.assertEqual(set(order), set(wanted))
        self.assertFalse(proof["violations"])
        self.assertEqual(proof, evaluate(confirmed, order))

    def test_cross_river_transfer_can_fit_by_reordering_existing_stops(self):
        old = ["汉口江滩", "知音号", "武汉天地", "张之洞与武汉博物馆", "古琴台", "汉阳造"]
        required = old + ["黎黄陂路"]
        c = {**new_contract(), "origin": "汉口站", "must": ["古琴台", "黎黄陂路"]}
        order, proof = solve(c, old, [], add=required, reoptimize=True)
        self.assertEqual(set(order), set(required))
        self.assertFalse(proof["violations"])
        self.assertLessEqual(proof["arrival"], c["end"])

    def test_advertised_arrival_hubs_can_be_used_as_pickup_endpoints(self):
        from kernel_tools import resolve
        for hub, station in GATEWAYS.items():
            with self.subTest(hub=hub):
                self.assertEqual(resolve(station)[0], hub)
                self.assertIn(hub, ATLAS_POINTS)
                self.assertTrue(self.box.find_place(hub)["places"][0]["can_anchor_trip"])
                leg = choose("江汉路", hub, {"rules": []}, 840, {})
                self.assertNotEqual(leg["mode"], "estimate")
        box = Toolbox(self.agent, {}, [])
        self.assertTrue(box.call("plan_trip", {"days": 1, "origin": "江汉路", "destination": "武汉站", "end": "16:30",
                                             "must": [{"place": "黎黄陂路"}]})["ok"])
        old = deepcopy(box.draft["days"]["1"])
        self.assertTrue(box.call("edit_trip", {"day": 1, "actions": [{"type": "set_destination", "place": "汉口站"}]})["ok"])
        new = box.draft["days"]["1"]
        self.assertEqual(set(old["order"]), set(new["order"]))
        self.assertEqual(old["contract"]["end"], new["contract"]["end"])
        self.assertEqual(new["audit"]["legs"][-1]["destination"], "汉口站")
