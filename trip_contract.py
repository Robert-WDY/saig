"""Ground travel-party requirements in the visitor's words before scheduling."""
import json
import re
from copy import deepcopy
from pathlib import Path
from semantics import arr, enum, obj, STRING
from places import PLACES

GUIDES = json.loads((Path(__file__).parent/"data/trip_guides.json").read_text("utf8"))
CITY_SOURCE = "https://wlj.wuhan.gov.cn/ztzl_27/wqzt/hyhbdkdwh/gzdt/202008/t20200828_1438954.shtml"
FIELDS = ("人数","成人数","儿童数","成员","单段步行上限米","交通方式","交通偏好","每日全团交通预算元",
          "全程全团交通预算元","每车每段固定报价元","住宿锚点","出行日期")
NUMERIC = {"人数","成人数","儿童数","单段步行上限米","每日全团交通预算元","全程全团交通预算元","每车每段固定报价元"}

def read_trip(model, question, memory, mode):
    clauses=[s.strip() for s in re.split(r"[，,。！？!?；;]",question) if s.strip()] or [question]
    schema = obj({"天数":{"type":"integer","minimum":1,"maximum":7},"行动":enum(["新建","改线","试排","非行程"]),
        "明确只游半天的日期":arr({"type":"integer","minimum":1,"maximum":7}),
        "攻略":enum(["组合",*[g["id"] for g in GUIDES]]),"必须按原站序完整保留":{"type":"boolean"},
        "指定游览先后":arr(obj({"日":{"type":"integer","minimum":1,"maximum":7},"先":enum(PLACES),"后":enum(PLACES),"原文":STRING})),
        "改动":arr(obj({"日期":arr({"type":"integer","minimum":1,"maximum":7}),"对象":STRING,
            "字段":enum(FIELDS),"值":STRING,"操作":enum(["设置","撤销"]),"原文":STRING})),
        "仍需核实的硬要求":arr(obj({"类型":enum(["场内或全天累计步行","设施或无障碍保证","包含非交通支出的硬预算","实时班次或实际到达保证","无法确定哪人在场或报价单位"]),
                                    "片段":enum(clauses)}))})
    options = {g["id"]:{"名称":g["title"],"天数":len(g["days"]),"时长":g["span"],"站点":g["days"]} for g in GUIDES}
    data = model.ask("""把游客的旅行委托提取为结构化资料。新建时天数必须覆盖整个旅行。改线只提取本轮明确新增或撤销的要求。
攻略优先选总天数及各日主题合适的原版；无匹配选组合。只有明确要求不裁剪原版站点才标必须完整。
只有明确要求两个游览站谁先谁后时提取游览先后，逐字摘出包括两站的依据。起点、住宿和赶车终点另行处理。
每项写所有实际生效的旅行日序，区分只参加某天的人与全团。只抄原文可证明的事项，原文逐字连续摘出。
人数填实际当日在场总数，只有人数明确或各成员可无歧义相加才填；成人数、儿童数、成员可另外保留。 
交通方式是硬性限定，值 walk/metro/taxi/transit，多种用逗号分隔；仅偏好用交通偏好 fastest/less_walk/fewer_changes/cheap/metro/taxi/walk。
单段步行上限米只用于景点之间转场；园内或全程累计步行保证、轮椅可达性等无法审核要求须原文列入仍需核实。
预算只接受明确的全团交通预算（按天或整趟），每人交通预算只有人数与范围明确时可换算。区分估价和每辆车每段已确认的一口价。
人数、预算、步行等数值用阿拉伯数字，住宿锚点只能取目录中的明确地点。出行日期为明确可推导的 YYYY-MM-DD，不猜年份。
普通兴趣、游览时段和必去点由另一个排程模块处理，不在改动中重复，也不要报告为缺数据。
如果仅要求地铁出行无需选择同名的地铁旅游攻略。具体班次或设施保证、全包预算等超出可审核范围的硬要求必须列出。
只有确实要求交付或修改行程才选旅行行动，索取一个公共事实不算。""",
        {"游客":question,"可引用的片段":clauses,"已有各日":memory["days"],"动作初判":mode,"目录":list(PLACES),"攻略":options},1800,schema)
    pending=[]
    for item in data["仍需核实的硬要求"]:
        decision=model.ask("判断这一明确的硬要求是否真的出现在原文中。询问规划、普通必去点、"
            "修改停留时间、人数、出发和到达时刻、预留进站时间均已有专门审核，不等于要求保证实时结果。"
            "要求同伴单段转场步行上限也由路网审核。原句没有提出这种额外保证时选否。",
            {"待核实类型":item["类型"],"原文":item["片段"]},45,obj({"确实要求":{"type":"boolean"}}))
        if decision["确实要求"]:pending.append(item["片段"])
    data["仍需核实的硬要求"]=pending
    if data["改动"]:
        proposed={str(i):row for i,row in enumerate(data["改动"])}
        reviewed=model.ask("独立核验每一项拟写入的旅行条件，逐项检查字段含义、人物、日期和数值是否与原话对应，只保留有依据的编号。"
            "赶车地点、游览地点和集合点不能自动充当住宿地。游览时长不是步行上限。"
            "另按实际在场日期填写游客给足信息的总人数：分组人数是组成；已完整列举成员时相加，某人中途加入只计参加日。"
            "未提人数的日期、或只是以前提过而本轮没有变更人数，一律不填。证据取完整原句片段。",
            {"完整原话":question,"总天数":data["天数"],"已有各日":memory["days"],"拟写":proposed},550,
            obj({"有效编号":arr(enum(proposed)),"当日总人数":arr(obj({"日":{"type":"integer","minimum":1,"maximum":7},
                  "人数":{"type":"integer","minimum":1,"maximum":10000},"依据":arr(enum(clauses))}))}))
        data["改动"]=[row for k,row in proposed.items() if k in reviewed["有效编号"]]
        for group in reviewed["当日总人数"]:
            if not group["依据"]:continue
            for row in data["改动"]:
                if row["字段"]=="人数" and group["日"] in row["日期"]:
                    row["日期"]=[d for d in row["日期"] if d!=group["日"]]
            data["改动"]=[row for row in data["改动"] if row["日期"]]
            data["改动"].append({"日期":[group["日"]],"对象":"","字段":"人数","值":str(group["人数"]),
                              "操作":"设置","原文":group["依据"][0],"依据片段":group["依据"]})
    for edge in data["指定游览先后"]:
        if not edge["原文"] or edge["原文"] not in question or any(edge[k] not in edge["原文"] for k in ("先","后")) or edge["先"]==edge["后"]:
            raise ValueError("请明确哪一天从哪个游览站先去哪个游览站。")
    for item in list(data["改动"]):
        if not item["原文"].strip() or item["原文"] not in question or not item["日期"]:
            raise ValueError("同行或交通条件的原文、日期不明确，请说明。")
        if any(day>data["天数"] for day in item["日期"]) and mode=="plan":
            raise ValueError("同行条件超出旅行日期。")
        field,val=item["字段"],item["值"]
        if item["操作"]=="撤销":
            continue
        if field in ("交通方式","交通偏好","住宿锚点"):
            service=model.ask("原句讲的是哪种行为？先区分乘坐离开武汉或抵达武汉的长途交通、接送会合、"
                "在武汉景点之间怎么移动以及过夜住宿。火车的出发时刻只约束到站；赶上这趟车不表示市内也要坐公共交通。"
                "若仅描述目的地或会面地，不得绑定为住宿。",{"原句":item["原文"],"完整请求":question},65,
                obj({"行为":arr(enum(["明确约定市内转场方式","明确约定过夜地点","对外交通或末端约定","其他"]))}))
            required="明确约定过夜地点" if field=="住宿锚点" else "明确约定市内转场方式"
            if required not in service["行为"]:
                data["改动"].remove(item)
                continue
        if field in NUMERIC:
            if not val.isdecimal() or int(val)>1000000 or (field=="人数" and int(val)<1):
                raise ValueError("无法核实人数、费用或距离的数值。")
            item["值"]=int(val)
        if field=="交通方式" and not set(val.split(","))<={"taxi","walk","metro","transit"}:
            raise ValueError("交通方式未核实。")
        if field=="交通偏好" and val not in ("fastest","less_walk","fewer_changes","cheap","metro","walk","taxi"):
            raise ValueError("交通偏好未核实。")
        if field=="住宿锚点" and val not in PLACES:
            raise ValueError("请提供酒店对应的已核实地点或集合点。")
        if field=="出行日期":
            from datetime import date
            try:
                date.fromisoformat(val)
            except ValueError:
                meaning=model.ask("原句明确指定了一个实际日历日期吗？只提到几点、行程的第几天或停留多久均答否。",
                                  item["原文"],40,obj({"有日历日期":{"type":"boolean"}}))
                if meaning["有日历日期"]:raise ValueError("请确认具体的出游年月日。")
                data["改动"].remove(item)
    return data

def mobility_for(old, changes, day):
    rules=deepcopy(old.get("rules",[]))
    for item in changes:
        if day not in item["日期"]:
            continue
        key=(item["字段"],item["对象"] if item["字段"] in ("成员","单段步行上限米") else "")
        rules=[r for r in rules if (r["field"],r["subject"])!=key]
        if item["操作"]=="设置":
            rules.append(dict(field=key[0],subject=key[1],value=item["值"],quote=item["原文"],
                              **({"evidence":item["依据片段"]} if item.get("依据片段") else {})))
    return {**old,"rules":rules}

def trip_review(days):
    """Inspect the complete proposed snapshot, including dates outside the current edit."""
    from places import region
    dates=sorted(days,key=int)
    per_day={}
    visited={}
    handoffs=[]
    limits=[]
    costs=[]
    for index,key in enumerate(dates):
        card=days[key]
        c=card["contract"]
        audit=card["audit"]
        values=settings(c.get("mobility",{"rules":[]}))
        if "全程全团交通预算元" in values:limits.append(values["全程全团交通预算元"])
        costs.append(audit.get("group_fare_bound"))
        names=[n for n in [c["origin"],*card["order"],c["destination"]] if n]
        per_day[key]={"visit_minutes":sum(s["end"]-s["start"] for s in audit["stops"]),
                      "transfer_minutes":sum(s["leg"] for s in audit["stops"])+audit["last_leg"],
                      "cross_region_legs":sum(region(a)!=region(b) for a,b in zip(names,names[1:])),
                      "free_after_minutes":c["end"]-audit["arrival"]-c["buffer"]}
        for n in card["order"]:visited.setdefault(n,[]).append(key)
        if index:
            prev=days[dates[index-1]]["contract"]["destination"]
            handoffs.append({"from_day":dates[index-1],"to_day":key,"previous_end":prev,"next_start":c["origin"],
                             "status":"同一锚点" if prev and prev==c["origin"] else "分开集合" if prev and c["origin"] else "住宿衔接未指定"})
    total=sum(costs) if None not in costs else None
    if limits and (total is None or total>min(limits)):
        raise ValueError("全程全团交通预算无法满足，原行程已保留。")
    return {"days":per_day,"revisits":{n:ks for n,ks in visited.items() if len(ks)>1},
            "overnights":handoffs,"group_transport_fare_bound":total}

def rebind_overnights(ops,cards):
    """A changed night's lodging affects its return and the linked departure next morning."""
    by_day={op["day"]:op for op in ops}
    for op in list(ops):
        day=op["day"]
        card=cards.get(str(day),{})
        old=card.get("contract",{})
        prev=settings(old.get("mobility",{"rules":[]})).get("住宿锚点")
        hotel=settings(op.get("mobility",{"rules":[]})).get("住宿锚点")
        if not hotel or hotel==prev:continue
        # A confirmed train or other separate endpoint must not be overwritten implicitly.
        if old.get("destination") not in (None,prev) and not op["set"].get("destination"):
            raise ValueError("新住宿与原来必须抵达的终点不同，请确认当晚最后一站。")
        op["set"].setdefault("destination",hotel)
        following=cards.get(str(day+1),{}).get("contract",{})
        if not following or not prev or following.get("origin")!=prev:continue
        successor=by_day.get(day+1)
        if not successor:
            successor={"day":day+1,"query":"调整住宿后的次日集合点","set":{},
                       "mobility":deepcopy(following.get("mobility",{"rules":[]})),"add":list(cards[str(day+1)]["order"])}
            ops.append(successor)
            by_day[day+1]=successor
        successor["set"].setdefault("origin",hotel)

def settings(mobility):
    rules=mobility["rules"]
    values={r["field"]:r["value"] for r in rules}
    caps=[r["value"] for r in rules if r["field"]=="单段步行上限米"]
    if caps: values["单段步行上限米"]=min(caps)
    if "人数" not in values and "成人数" in values and "儿童数" in values:
        values["人数"]=values["成人数"]+values["儿童数"]
    if any(values.get(k,0)>values.get("人数",10**9) for k in ("成人数","儿童数")) or (
        "人数" in values and values.get("成人数",0)+values.get("儿童数",0)>values["人数"]):
        raise ValueError("成人、儿童和当日总人数矛盾。")
    return values

