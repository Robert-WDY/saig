import unittest
from places import PLACES
from planning import evaluate, new_contract
from transport import choose

def rules(**fields):
    return {"rules":[{"field":k,"subject":"","value":v,"quote":"本用例的结构化输入"} for k,v in fields.items()]}

class Polish(unittest.TestCase):
    def test_no_walk_estimate_across_the_river(self):
        leg=choose("武昌江滩","晴川阁",{"rules":[]},600,{})
        self.assertNotEqual(leg["mode"],"walk")
        with self.assertRaises(ValueError):
            choose("武昌江滩","晴川阁",rules(单段步行上限米=1700),600,{})

    def test_estimate_does_not_prove_walking_cap(self):
        self.assertEqual(choose("黎黄陂路","巴公房子",{"rules":[]},600,{})["mode"],"walk")
        with self.assertRaises(ValueError):
            choose("黎黄陂路","巴公房子",rules(单段步行上限米=2000),600,{})

    def test_fastest_leg_rescues_a_tight_day(self):
        fast=choose("江汉路","吉庆街",{"rules":[]},600,{},True)
        self.assertLess(fast["minutes"],choose("江汉路","吉庆街",{"rules":[]},600,{})["minutes"])
        c={**new_contract(),"origin":"江汉路","start":600,"end":600+fast["minutes"]+PLACES["吉庆街"]["minutes"]}
        proof=evaluate(c,["吉庆街"])
        self.assertFalse(proof["violations"])
        self.assertEqual(proof["legs"][0]["mode"],fast["mode"])

    def test_topics_survive_public_mode(self):
        from serve import reply_topics
        result={"mode":"info","days":{"1":{}},"trace":[{"tool":"community","query":"q"},
                {"step":"answered_question","tool_name":"saig","supported":True}]}
        self.assertEqual(reply_topics(result),["数命 SPU 社区","SAIG 大赛"])
        self.assertEqual(reply_topics({**result,"mode":"edit"})[0],"旅游规划")

if __name__=="__main__":
    unittest.main()
