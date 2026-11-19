"""Compile option-specific requirements from the visitor's actual clauses."""
from copy import deepcopy
import re
import unicodedata

from places import PLACES
from planning import Invalid
from quantities import NUM, clocks, durations, number
from semantics import STRING, arr, enum, obj
from visitor_turn import clock_value

FIELDS=("start","end","origin","destination","buffer","max_stops","only","must","avoid","drop",
        "duration","shift_start","shift_end","lighter")

def compile_options(model,tasks,catalog):
    work={}
    for task in tasks:
        if task["kind"]=="revise" and task["inputs"][0] in catalog:
            days=catalog[task["inputs"][0]]["days"]
            scope=task["target_days"]
        elif task["kind"]=="plan" and task["constraints"]:
            days={}
            scope=list(range(1,task["days"]+1))
        else:
            continue
        work[task["id"]]={
            "方案":task["title"],"可修改的日期":scope,"请求":task["request"],
            "条件":list(dict.fromkeys([task["source"],*task["constraints"]])),
            "旧日卡":{n:{"约束":c["contract"],"站点":c["order"]} for n,c in days.items()}
        }
    if not work:return {}
    change=obj({"day":{"type":"integer","minimum":1,"maximum":7},"field":enum(FIELDS),
                "values":arr(STRING),"evidence":{"type":"integer","minimum":1},
                "mentions":arr(STRING)},required=["day","field","values","evidence"])
    schema=obj({"items":arr(obj({"task":enum(work),"changes":arr(change),"requires_full_planner":{"type":"boolean"}}))})
    reply=model.ask("""按方案及日期将明确要求转成操作。每个任务独立输出一项。
同一适用条件要在每个目标日分别输出。禁止跨方案取条件。保持不变的字段和日期不产生操作。
evidence 填本任务「条件」内从 1 开始的原文编号，数字和地名必须能从该原句核实。
start、end 用 24 小时 HH:MM。要在几点到车站，填 end 和 destination；若车在几点开、提前多少分钟到，把绝对时刻填 end，提前分钟填 buffer。
shift_start、shift_end 用带符号分钟数，推迟为正。buffer、max_stops 填数字字符串。
origin/destination/must/avoid/drop 用目录里的地点名。若游客用了简称，mentions 按地点顺序逐字摘出原话里的称呼。only 用用户明确说只游览的全部地点，程序据此设必去与上限。
「不去某站、改去某站」可拆成 drop 与 must。duration 的 values 为地点名、停留分钟数。想轻松或降低景点密度时填 lighter，values 留空。
若有以上无法表达的硬限制，如交通类型、预算、住宿或特定参观窗口，标 requires_full_planner。出游背景、旅行天数、未确定的周末或初次到访等不产生操作，也无需完整规划器。""",
        {"任务":work,"地点目录":list(PLACES)},2100,schema)
    by_id={}
    for item in reply["items"]:
        key=item["task"]
        if key in by_id:raise Invalid("同一方案收到了重复的约束清单。")
        by_id[key]=item
    return {key:(by_id.get(key),context) for key,context in work.items()}

def one_value(values):
    if len(values)!=1:raise Invalid("该约束应有且仅有一个值。")
    return values[0]

def integer(value):
    if not re.fullmatch(r"[+-]?\d+",value):raise Invalid("约束数值缺少有效整数。")
    return int(value)

def places(values,quote,mentions,prior,*,other_clauses=()):
    if not values or len(set(values))!=len(values) or any(n not in PLACES for n in values):
        raise Invalid("地点缺少游客原句或已核实位置。")
    contract=prior.get("contract",{})
    anchors=set(prior.get("order",[]))|{contract.get("origin"),contract.get("destination")}
    def resolves(mention,name):
        if len(mention)<2 or mention not in quote:return False
        shortened=".*".join(map(re.escape,mention))
        choices=[n for n in PLACES if re.search(shortened,n)]
        previous=[n for n in choices if n in anchors]
        return (previous or choices)==[name]
    for i,name in enumerate(values):
        if name in quote:continue
        if sum(name in clause for clause in other_clauses)==1:continue
        mention=mentions[i] if i<len(mentions) else ""
        if resolves(mention,name):continue
        # Even when a mention field is missing, an existing stop can be retained
        # by an unambiguous shortening literally present in the scoped clause.
        if name in anchors and any(resolves(part,name) for size in range(2,len(name))
                                   for part in re.findall(rf"(?=([\u3400-\u9fff]{{{size}}}))",quote)):
            continue
        raise Invalid(f"地点简称无法唯一绑定到本方案：{name}。")
    return values

def clock_options(raw,quote):
    value=clock_value(raw,quote)
    choices=set()
    for start,end,literal in clocks(quote):
        hour,minute=map(int,literal.split(":"))
        clock=hour*60+minute
        if clock%720!=value%720:continue
        text=quote[start:end]
        if re.search(r"凌晨|清晨|早上|上午|中午|下午|傍晚|晚上|[:：]",text) or hour>=13:
            choices.add(clock)
        else:
            choices.update({clock,clock+720} if hour<12 else {clock})
    if not choices:raise Invalid("钟点缺少游客原句。")
    return value,choices

def compile_contract(task,base,bundle):
    if bundle is None:return None
    item,context=bundle
    if item is None:raise Invalid("该方案缺少独立的约束清单。")
    if item["requires_full_planner"]:return None
    scope=context["可修改的日期"]
    ops={n:{"day":n,"query":task["request"],"set":{},
            "mobility":deepcopy(base.get(str(n),{}).get("contract",{}).get("mobility",{"rules":[]}))}
         for n in scope}
    evidence=[]
    seen={}
    times={}
    for edit in item["changes"]:
        n,field,values=edit["day"],edit["field"],edit["values"]
        if n not in ops or not 1<=edit["evidence"]<=len(context["条件"]):
            raise Invalid("约束的方案、日期或游客原文超出允许范围。")
        quote=context["条件"][edit["evidence"]-1]
        if field not in ("must","avoid","drop","duration") and (n,field) in seen:
            if seen[n,field]!=values:raise Invalid("同一天的约束互相冲突。")
            continue
        seen[n,field]=values
        op=ops[n]
        original=base.get(str(n),{})
        prior=original.get("contract",{})
        mentions=edit.get("mentions",[])
        location_values=(values[:1] if field=="duration" else values) if field in (
            "origin","destination","duration","only","must","avoid","drop") else None
        if location_values is not None and len(scope)==1 and any(name not in quote for name in location_values):
            candidates=[clause for clause in context["条件"] if all(name in clause for name in location_values)]
            if len(candidates)==1:quote=candidates[0]
        if field in ("start","end"):
            raw=unicodedata.normalize("NFKC",one_value(values))
            if re.fullmatch(r"\d:\d{2}",raw):raw="0"+raw
            value,choices=clock_options(raw,quote)
            times[n,field]=choices
            if value not in choices:value=min(choices)
        elif field in ("shift_start","shift_end"):
            value=integer(one_value(values))
            field=field.removeprefix("shift_")
            if field not in prior or abs(value) not in durations(quote):raise Invalid("相对时间改动缺少原约定或时长依据。")
            value+=prior[field]
        elif field in ("origin","destination"):
            value=one_value(places(values,quote,mentions,original))
        elif field in ("buffer","max_stops"):
            value=integer(one_value(values))
            allowed=durations(quote) if field=="buffer" else [number(s) for s in re.findall(NUM,quote)]
            if value not in allowed and not (field=="buffer" and value==0):
                raise Invalid("分钟数或站数与原话不一致。")
        elif field=="duration":
            if len(values)!=2:raise Invalid("停留约束应包含景点与分钟数。")
            name=one_value(places(values[:1],quote,mentions,original))
            duration=integer(values[1])
            if duration not in durations(quote):raise Invalid("停留时长与原话不一致。")
            durations_by_place=op["set"].setdefault("durations",{})
            if name in durations_by_place and durations_by_place[name]!=duration:raise Invalid("同一景点的停留时长冲突。")
            durations_by_place[name]=duration
            op.setdefault("require",[]).append(name)
        elif field in ("only","must","avoid","drop"):
            names=places(values,quote,mentions,original,other_clauses=context["条件"] if len(scope)==1 else ())
            action={"only":"require","must":"require","avoid":"exclude","drop":"remove"}[field]
            op.setdefault(action,[]).extend(names)
            if field in ("avoid","drop"):op.setdefault("unrequire",[]).extend(names)
            if field=="only":
                op["_only"]=names
                op.setdefault("unrequire",[]).extend(n for n in prior.get("must",[]) if n not in names)
        else:
            op["_lighter"]=True
        if field in ("origin","destination","start","end","buffer","max_stops"):
            if field in op["set"] and op["set"][field]!=value:raise Invalid("同一天的约束互相冲突。")
            op["set"][field]=value
        evidence.append({"day":n,"field":edit["field"],"values":values,"quote":quote})
    if task["kind"]=="revise" and set(scope)!={item["day"] for item in evidence}:
        raise Invalid("修改日期缺少对应的条件。")
    for n,op in ops.items():
        prior=base.get(str(n),{})
        # For an unqualified closing time, inherit the day from its departure.
        # A clock with an explicit period or 24-hour notation has only one choice.
        start=op["set"].get("start",prior.get("contract",{}).get("start",540))
        end_choices=times.get((n,"end"),())
        if len(end_choices)>1:
            possible=[minute for minute in end_choices if minute>=start]
            if possible:op["set"]["end"]=min(possible)
        only=op.pop("_only",None)
        lighter=op.pop("_lighter",False)
        if only:
            if set(op.get("require",[]))!=set(only):raise Invalid("仅游览的景点与额外必去点冲突。")
            existing=op["set"].get("max_stops")
            if existing is not None and existing<len(only):raise Invalid("指定游览地点超过站数上限。")
            op["set"]["max_stops"]=len(only)
        elif lighter:
            old_limit=prior.get("contract",{}).get("max_stops",12)
            old_stops=len(prior.get("order",[]))
            cap=max(1,min(3,old_stops-1)) if old_stops else 3
            must=set(prior.get("contract",{}).get("must",[]))-set(op.get("unrequire",[]))
            minimum=len(must|set(op.get("require",[])))
            op["set"]["max_stops"]=min(op["set"].get("max_stops",old_limit),max(cap,minimum))
    for binding in evidence:
        field=binding["field"]
        if field in ("start","end","shift_start","shift_end","lighter"):
            key="max_stops" if field=="lighter" else field.removeprefix("shift_")
            binding["effective_value"]=ops[binding["day"]]["set"][key]
    mode="plan" if task["kind"]=="plan" else "preview" if task["preview"] else "edit"
    return {"mode":mode,"days":list(ops.values())},evidence
