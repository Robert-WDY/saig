"""Regression checks on saved visitor cards, independent of model phrasing."""
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from agent import Agent
from kernel_tools import Toolbox
from route_edits import edit_route


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
