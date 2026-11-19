"""Deterministic checks at the scope and scheduling boundaries."""
from copy import deepcopy
import unittest

from agent import apply_constraints
from deliverables import check_days, order_tasks
from option_conditions import compile_contract, places
from planning import Invalid, evaluate

def request(key,kind,refs,days=()):
    return {"id":key,"kind":kind,"title":key,"request":key,"source":"原话",
            "constraints":[],"inputs":refs,"target_days":list(days),"compare_prior":False}

def day(start):
    order=["黄鹤楼"]
    contract=apply_constraints({},{"set":{"start":start}})
    return {"contract":contract,"order":order,"audit":evaluate(contract,order)}

class OptionScopeTests(unittest.TestCase):
    def test_missing_model_mention_can_recover_an_anchored_shortening(self):
        prior={"order":["湖北省博物馆"]}
        self.assertEqual(places(["湖北省博物馆"],"省博还是要去",[],prior),["湖北省博物馆"])
        with self.assertRaisesRegex(Invalid,"简称"):
            places(["湖北省博物馆"],"去黄鹤楼",[],prior)

    def test_compare_uses_revision_even_if_the_proposed_graph_used_the_old_id(self):
        old={"long":{"days":{"1":day(540),"2":day(600)}},"short":{"days":{"1":day(540)}}}
        change=request("edit","revise",["long"],[2])
        comparison=request("comparison","compare",["short","long"])
        self.assertEqual(order_tasks([comparison,change],old,"原话"),("edit","comparison"))
        self.assertEqual(comparison["inputs"],["short","edit"])

    def test_schedule_rejects_changes_on_untargeted_days(self):
        old={"1":day(540),"2":day(600)}
        new=deepcopy(old)
        new["1"]=day(610)
        with self.assertRaisesRegex(Invalid,"未授权日期"):
            check_days(new,2,old,[2])

    def test_schedule_rejects_feasible_but_cross_assigned_constraints(self):
        old={"1":day(540),"2":day(600)}
        new=deepcopy(old)
        new["2"]=day(660)
        compiled={"days":[{"day":2,"set":{"start":630}}]}
        with self.assertRaisesRegex(Invalid,"未使用该方案"):
            check_days(new,2,old,[2],compiled)

    def test_day_scope_and_inherited_period(self):
        task={"kind":"revise","request":"更改第二天","preview":True}
        base={"1":day(540),"2":day(600)}
        context={"可修改的日期":[2],"条件":["上午八点出门","八点十五分结束"]}
        changes=[{"day":2,"field":"start","values":["8:00"],"evidence":1},
                 {"day":2,"field":"end","values":["20:15"],"evidence":2}]
        item={"requires_full_planner":False,"changes":changes}
        spec,_=compile_contract(task,base,(item,context))
        self.assertEqual(spec["days"][0]["set"],{"start":480,"end":495})
        changes[1]["day"]=1
        with self.assertRaisesRegex(Invalid,"超出允许范围"):
            compile_contract(task,base,(item,context))

if __name__=="__main__":
    unittest.main()
