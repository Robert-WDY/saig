import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock
from unittest.mock import patch
from agent import Agent, apply_constraints, apply_facts
from knowledge import Knowledge
from places import PLACES, locate
from planning import Invalid, evaluate, new_contract, solve
from storage import Conflict, Sessions

class Verification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb=Knowledge()

    def test_sources_and_guide(self):
        for p in PLACES.values():
            self.assertIn(p["evidence"],self.kb.by_id)
        self.assertTrue(locate("智民里")["catalog"][0]["map_url"])
        self.assertGreater(len({r["locator"] for r in self.kb.rows if r["category"]=="guide"}),30)

    def test_named_attraction_opens_its_article(self):
        hit=self.kb.search("黄鹤楼",["attraction"],1)[0]
        self.assertEqual(hit["id"],"book.6.1")

    def test_exact_boundary(self):
        c={**new_contract(),"origin":"江汉路","must":["智民里"],"destination":"汉口站","end":900,"buffer":20}
        from transport import choose
        legs=[choose(a,b,{"rules":[]},600,{})["minutes"] for a,b in (("江汉路","智民里"),("智民里","汉口站"))]
        c["start"]=900-20-sum(legs)-PLACES["智民里"]["minutes"]
        self.assertFalse(evaluate(c,["智民里"])["violations"])
        c["start"]+=1
        self.assertTrue(evaluate(c,["智民里"])["violations"])

    def test_minimal_and_deadline(self):
        c={**new_contract(),"origin":"江汉路","must":["智民里"],"start":600,"end":700}
        prior=["黎黄陂路","智民里"]
        route,proof=solve(c,prior,["户部巷"])
        self.assertEqual(route,["智民里"])
        self.assertEqual(proof,evaluate(c,route))
        self.assertEqual(prior,["黎黄陂路","智民里"])

    def test_window(self):
        c={**new_contract(),"windows":{"智民里":[600,630]},"must":["智民里"]}
        with self.assertRaises(Invalid):
            solve(c,[],["智民里"])

    def test_replacing_one_object_keeps_other_stops_in_order(self):
        c=new_contract()
        old=["江汉路","黎黄陂路","智民里"]
        old_stops=evaluate(c,old)["stops"]
        new,proof=solve(c,old,[],["吉庆街"],["黎黄陂路"],old_stops,[("黎黄陂路","吉庆街")])
        self.assertEqual(new,["江汉路","吉庆街","智民里"])
        self.assertFalse(proof["violations"])

    def test_area_and_soft_guide_cannot_override_hard_contract(self):
        c={**new_contract(),"regions":["汉口"],"must":["智民里"],"max_stops":1}
        route,_=solve(c,[],["昙华林","黎黄陂路","智民里"])
        self.assertEqual(route,["智民里"])

    def test_unapproved_hard_constraint_is_not_dropped(self):
        with self.assertRaises(Invalid):
            apply_constraints(new_contract(),{"set":{"wheelchair_access_confirmed":True}})

    def test_failed_guide_replans_with_the_frozen_contract(self):
        rows=[{"id":"west","text":"昙华林"},{"id":"east","text":"黎黄陂路"}]
        model=Mock()
        model.ask.side_effect=[{"id":"west","order":["昙华林"]},{"query":"汉口老街"}]
        with tempfile.TemporaryDirectory() as folder:
            a=Agent(str(Path(folder)/"a.db"),model=model,kb=self.kb)
            trace=[]
            with patch.object(a,"tool",return_value=rows):
                card=a.day("1",{"set":{"regions":["汉口"]},"query":"老建筑"},None,trace)
        self.assertEqual(card["order"],["黎黄陂路"])
        self.assertEqual(card["contract"]["regions"],["汉口"])
        self.assertTrue(any(step.get("audit_error") for step in trace))
        self.assertTrue(any(step.get("replan") for step in trace))

    def test_revoke_and_keep(self):
        c=apply_constraints(new_contract(),{"require":["智民里"],"set":{"end":850}})
        revised=apply_constraints(c,{"unrequire":["智民里"],"set":{"start":600}})
        self.assertEqual((c["must"],revised["must"],revised["end"]),(["智民里"],[],850))

    def test_object_ownership(self):
        state={"facts":[]}
        for who,what in [("妈妈","老建筑"),("我","江景"),("妈妈","过早")]:
            sentence=who+"喜欢"+what
            apply_facts(state,[dict(subject=who,relation="偏好",object=what,quote=sentence)],sentence)
        self.assertEqual([(f["subject"],f["object"]) for f in state["facts"]],[("我","江景"),("妈妈","过早")])
        with self.assertRaises(Invalid):
            apply_facts(state,[dict(subject="我",relation="名字",object="小明",quote="我是小明")],"我没说过")

    def test_transaction_and_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Sessions(str(Path(folder)/"s.db"))
            rev,state,_=db.read("a","1","q")
            self.assertEqual(db.save("a","1","q",rev,state,{"ok":1}),{"ok":1})
            self.assertEqual(db.save("a","1","q",rev,state,{"ok":2}),{"ok":1})
            with self.assertRaises(Conflict):
                db.save("a","2","q",rev,state,{})
            with self.assertRaises(Conflict):
                db.read("a","1","changed")
            self.assertEqual(db.read("b","1","q")[0],0)

    def test_preview_and_atomic_multiday_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            model=Mock()
            model.ask.return_value={}
            a=Agent(str(Path(folder)/"a.db"),kb=self.kb,model=model)
            spec={"mode":"plan","days":[{"day":1,"require":["智民里"]},{"day":2,"require":["昙华林"]}]}
            with patch.object(a,"understand",return_value=spec):
                first=a.respond("u","原始计划")
            original=first["days"]
            self.assertEqual(set(original),{"1","2"})
            with patch.object(a,"understand",return_value={"mode":"preview","days":[{"day":2,"set":{"start":610}}]}):
                view=a.respond("u","看看")
            self.assertEqual(view["days"],original)
            self.assertEqual(view["preview"]["1"],original["1"])
            broken={"mode":"edit","days":[{"day":2,"set":{"start":620}},{"day":1,"set":{"origin":"未核实酒店"}}]}
            with patch.object(a,"understand",return_value=broken):
                r=a.respond("u","两个修改")
            self.assertEqual(r["mode"],"clarify")
            self.assertEqual(r["days"],original)

if __name__=="__main__":
    unittest.main()
