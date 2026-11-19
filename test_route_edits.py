import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from planning import Invalid, evaluate, new_contract
from places import city_places, transit
from route_edits import edit_route
from storage import Conflict, Sessions


def card(names, **kwargs):
    c = {**new_contract(), **kwargs}
    return {"order":names,"contract":c,"audit":evaluate(c,names)}


class RouteEditTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Sessions(str(Path(folder.name)/"test.db"))
        self.first = card(["黄鹤楼"])
        self.second = card(["江汉路","黎黄陂路"],destination="汉口站",end=960,must=["江汉路"])
        self.days = {"1":self.first,"2":self.second}
        self.state = {"days":{"1":self.first},"pending_days":{"1":self.second},"facts":[],"turns":[],
                      "options":{"two":{"days":self.days,"title":"两日游","version":1}}}
        self.store.save("s","seed","seed",0,self.state,{})
        self.change = {"plan":"two","day":"2","remove":["江汉路"],"add":["吉庆街"],
                       "basis":{k:self.second[k] for k in ("order","contract")}}

    def test_scoped_batch_replan_and_retry(self):
        result = edit_route(self.store,"s","r",self.change)
        second = result["cards"]["2"]
        self.assertEqual(set(second["order"]),{"黎黄陂路","吉庆街"})
        self.assertEqual(second["contract"]["must"],["吉庆街"])
        self.assertLessEqual(second["audit"]["arrival"],960)
        self.assertEqual(second["audit"],evaluate(second["contract"],second["order"]))
        self.assertEqual(result["cards"]["1"],self.first)
        self.assertEqual(result,edit_route(self.store,"s","r",self.change))
        with self.assertRaises(Conflict):
            edit_route(self.store,"s","stale",self.change)
        rev,state,_ = self.store.read("s","read","")
        self.assertEqual(rev,2)
        self.assertEqual(state["days"],self.state["days"])
        self.assertEqual(state["pending_days"],self.state["pending_days"])
        self.assertEqual(state["options"]["two"]["version"],2)

    def test_infeasible_edit_rolls_back(self):
        tight = card(["江汉路"],start=900,end=950)
        state = deepcopy(self.state)
        state["days"]={"1":tight}
        self.store.save("tight","seed","seed",0,state,{})
        change={"plan":"current","day":"1","basis":{k:tight[k] for k in ("order","contract")},"add":["黄鹤楼"],"remove":[]}
        with self.assertRaises(Invalid):
            edit_route(self.store,"tight","r",change)
        self.assertEqual(self.store.read("tight","read","")[:2],(1,state))

    def test_preview_isolated_and_empty_day_rejected(self):
        change={**self.change,"plan":"preview","day":"1","add":[],"remove":["江汉路","黎黄陂路"]}
        with self.assertRaises(Invalid): edit_route(self.store,"s","r",change)
        change["remove"]=["黎黄陂路"]
        result=edit_route(self.store,"s","r",change)
        self.assertEqual(result["cards"]["1"]["order"],["江汉路"])
        state=self.store.read("s","read","")[1]
        self.assertEqual(state["days"],self.state["days"])
        self.assertEqual(state["options"],self.state["options"])

    def test_first_map_selection_persists_for_chat_and_retry(self):
        change = {"plan":"new","day":"1","add":["华中师范大学","户部巷"],"remove":[]}
        result = edit_route(self.store,"new-visitor","one",change)
        self.assertEqual(result,edit_route(self.store,"new-visitor","one",change))
        self.assertEqual(result["plan_id"],"current")
        card = result["cards"]["1"]
        self.assertEqual(set(card["order"]),set(change["add"]))
        self.assertEqual(card["audit"]["violations"],[])
        state = self.store.read("new-visitor","read","")[1]
        self.assertEqual(state["days"],result["cards"])
        self.assertEqual(len(state["turns"]),1)

    def test_map_creates_independent_option_with_existing_preview(self):
        change = {"plan":"new","day":"1","add":["武汉大学"],"remove":[]}
        result = edit_route(self.store,"s","new-option",change)
        state = self.store.read("s","read","")[1]
        for slot in ("days","pending_days"):
            self.assertEqual(state[slot],self.state[slot])
        self.assertEqual(state["options"]["two"],self.state["options"]["two"])
        self.assertEqual(state["options"][result["plan_id"]]["days"],result["cards"])

    def test_malformed_first_selection_writes_nothing(self):
        for names in [[],["未知景点"],["武汉大学","武汉大学"]]:
            with self.assertRaises(Invalid):
                edit_route(self.store,"empty","new",{"plan":"new","day":"1","add":names,"remove":[]})
            self.assertEqual(self.store.read("empty","read","")[0],0)

    def test_directory_coverage_and_unavailable_places(self):
        atlas = city_places()
        self.assertEqual(len({r["official_name"] for r in atlas if r.get("official_name")}),72)
        self.assertEqual(len(atlas),len({r["name"] for r in atlas}))
        for r in atlas:
            if r["plannable"]:
                self.assertIsNotNone(r["point"])
                self.assertFalse(r.get("notice"))
                self.assertGreater(r["minutes"],0)
        unavailable = next(r["name"] for r in atlas if not r["plannable"])
        with self.assertRaises(Invalid):
            edit_route(self.store,"s","blocked",dict(plan="new",day="1",add=[unavailable],remove=[]))

    def test_distant_scenic_stop_respects_a_train_deadline(self):
        far = transit("清凉寨","汉口站")
        self.assertGreater(far,transit("江汉路","汉口站"))
        tight = card(["江汉路"],start=600,end=820,destination="汉口站",buffer=20)
        original = {**self.state,"days":{"1":tight}}
        self.store.save("train","seed","seed",0,original,{})
        with self.assertRaises(Invalid):
            edit_route(self.store,"train","far",dict(plan="current",day="1",add=["清凉寨"],remove=[],
                       basis={k:tight[k] for k in ("order","contract")}))
        self.assertEqual(self.store.read("train","read","")[1]["days"],original["days"])
