import copy
import os
import unittest
from unittest.mock import Mock,patch

from agent import apply_constraints
from planning import evaluate,new_contract,solve,Invalid
from places import PLACES
from transport import choose,live_transit,metro_route,road
from trip_contract import GUIDES,mobility_for,settings,trip_review,rebind_overnights

def rules(**fields):
    return {"rules":[{"field":k,"subject":"","value":v,"quote":"本用例的结构化输入"} for k,v in fields.items()]}

class TripAcceptance(unittest.TestCase):
    def test_source_days_link_only_catalog_objects(self):
        durations=set()
        for g in GUIDES:
            durations.add((g["span"],len(g["days"])))
            for names in g["days"]:
                self.assertEqual(len(names),len(set(names)))
                self.assertTrue(all(PLACES[n]["minutes"]>0 for n in names))
        self.assertTrue({("half",1),("day",1),("day",2),("day",3)}<=durations)

    def test_group_obligation_binds_subject_and_date(self):
        delta=[{"日期":[2],"对象":"祖母","字段":"单段步行上限米","值":500,"原文":"祖母每段最多500米","操作":"设置"}]
        first=mobility_for({},delta,1);second=mobility_for({},delta,2)
        self.assertNotIn("单段步行上限米",settings(first));self.assertEqual(second["rules"][0]["subject"],"祖母")
        revoked=mobility_for(second,[{**delta[0],"操作":"撤销"}],2)
        self.assertFalse(revoked["rules"]);self.assertEqual(settings(second)["单段步行上限米"],500)

    def test_directed_network_and_walking_cap(self):
        a,b="江汉路","江汉关"
        result=choose(a,b,rules(单段步行上限米=500),540,{})
        self.assertEqual(result["mode"],"walk")
        self.assertGreater(result["walk_m"],0);self.assertLessEqual(result["walk_m"],500)
        with self.assertRaises(ValueError):choose("江汉关","黎黄陂路",rules(单段步行上限米=500),540,{})

    def test_meter_estimate_cannot_certify_a_hard_fare(self):
        with self.assertRaisesRegex(ValueError,"估价"):
            choose("江汉路","江汉关",rules(人数=6,交通方式="taxi",每日全团交通预算元=1000),540,{})

    def test_total_compares_days_and_multiplies_cars(self):
        c={**new_contract(),"origin":"江汉路","mobility":rules(人数=6,交通方式="taxi",每车每段固定报价元=30,全程全团交通预算元=100)}
        audit=evaluate(c,["江汉关"]);self.assertFalse(audit["violations"])
        self.assertEqual(audit["group_fare_bound"],60)
        card={"contract":c,"order":["江汉关"],"audit":audit}
        with self.assertRaisesRegex(ValueError,"全程"):trip_review({"1":card,"2":card})
        self.assertEqual(trip_review({"2":card})["group_transport_fare_bound"],60)

    def test_metro_names_and_estimate_are_distinct_from_walking_evidence(self):
        trip=choose("黄鹤楼","汉口江滩",rules(交通方式="metro"),540,{})
        self.assertIn("司门口黄鹤楼",trip["directions"]);self.assertIn("黄浦路",trip["directions"]);self.assertIsNone(trip["walk_m"])
        with self.assertRaises(ValueError):choose("黄鹤楼","汉口江滩",rules(交通方式="metro",单段步行上限米=500),540,{})

    def test_provider_handoff_coordinates_date_direction_and_cache(self):
        def provider(url,params,timeout,allow_redirects):
            if "geocode" in url:
                data={"geocodes":[{"location":"114.1,30.5" if params["address"]=="起点" else "114.3,30.6","adcode":"420102","level":"兴趣点"}]}
            else:
                self.assertEqual((params["origin"],params["destination"],params["date"],params["time"]),("114.1,30.5","114.3,30.6","2026-12-03","10:15"))
                data={"route":{"transits":[{"duration":"1800","walking_distance":"270","cost":"3","segments":[{"bus":{"buslines":[{"name":"线路甲","type":"地铁","departure_stop":{"name":"上车站"},"arrival_stop":{"name":"下车站"}}]}}]}]}}
                data["route"]["transits"][0]["segments"][0]["railway"]={"via_stops":[],"alters":[],"spaces":[]}
            r=Mock();r.json.return_value={"status":"1",**data};return r
        with patch.dict(os.environ,{"SAIG_AMAP_KEY":"fixture"}),patch("transport.requests.get",side_effect=provider) as http:
            cache={}
            a=live_transit("起点","终点","2026-12-03",615,cache)
            self.assertEqual(a,live_transit("起点","终点","2026-12-03",615,cache))
            self.assertEqual(http.call_count,3);self.assertEqual((a[0]["minutes"],a[0]["walk_m"],a[0]["ticket"]),(30,270,3))
            self.assertIn("上车站",a[0]["directions"])

    def test_legacy_card_can_be_edited_and_audited(self):
        c=new_contract(); old=copy.deepcopy(c)
        new=apply_constraints(c,{"set":{},"mobility":rules(人数=2)})
        route,audit=solve(new,["江汉路","江汉关"],[])
        self.assertEqual(evaluate(new,route),audit);self.assertEqual(old,c)
        self.assertEqual(len(audit["legs"]),1)

    def test_changed_night_updates_adjacent_departure_only(self):
        original=rules(住宿锚点="江汉路")
        cards={"1":{"contract":{"destination":"江汉路","mobility":original}},
               "2":{"order":["智民里"],"contract":{"origin":"江汉路","destination":"汉口站","mobility":original}}}
        op={"day":1,"set":{},"mobility":rules(住宿锚点="昙华林")}
        changes=[op];rebind_overnights(changes,cards)
        self.assertEqual(changes[0]["set"],{"destination":"昙华林"})
        self.assertEqual(changes[1]["set"],{"origin":"昙华林"})
        self.assertEqual(cards["2"]["contract"]["destination"],"汉口站")

