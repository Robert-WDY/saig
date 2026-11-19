"""Compile one model interpretation into the same day, tool and memory contracts as the full planner."""
from copy import deepcopy
import re
from knowledge import TOOLS
from places import PLACES
from quantities import clocks,durations,NUM,number
from semantics import arr,enum,obj,STRING
from session_answers import evidence
from diagnostics import timed

FIELDS=("start","end","origin","destination","buffer","later_start","earlier_start","later_end","earlier_end","must","max_stops")
MODES=("info","plan","edit","preview","keep","confirm_preview","inspect_preview","detailed","compose")
INSTRUCTION="""你是武汉数命 SPU 城市 AI 接待员，接待武汉旅游、数命社区和 SAIG 比赛三类来访者。本项目中的选手报名、作品、人气评选均为 SAIG 竞赛事务，社区参访登记、开放时间归社区。若有其他明确主体则沿用游客所指。
一次理解游客本轮的全部委托，同时分出正式行程、假设、资料问题、可写入的偏好和只读事项。
每项 job 的所求答案类型用明确名词表示用户期待的值（食物名称、地点名称、时间、流程、概念等）。每条资料子问题保留原话所求对象的类型、粒度与数量，地点是范围时不要将它改写成所求对象。
普通单日行程可包含以下字段。每条都要附游客本轮的原文（逐字，尽量包含动作）。整段有空/能玩的时间范围属于全天 start 和 end，各自填当地24小时 HH:MM；单个景点的预约或入场窗口是另一种约束。
出门/集合地、游玩之前已经身处的地点是 origin，赶车或接人处是 destination；车到或车开时刻为 end，提前量单独填 buffer 分钟。相对改期选 later_start/earlier_start/later_end/earlier_end，填正的分钟数，未更改的字段不要重复生成。只逛指定地点要写 must，并用 max_stops 限制数量。普通新建单日建议保留游客兴趣供攻略检索。
预览不写正式卡。已有行程上问更动的效果、先看看，mode 为 preview；明确委托直接改才是 edit。单日原卡只有一天时可直接定位；已有多日正式卡时：只改明确点名的某一天（第N天）的出发或结束时间（含推迟、提前多久），选 edit；改站点、顺序、多天或没说哪天，选 detailed。两种情况都不得选 info 或 keep。没有原卡时修改或读卡不要虚构。needs_card 表示正在引用已经存在的正式卡，新建、查资料和根据偏好推荐均填 false。keep 只用于没有其他待办、单纯决定保留原样。只查看已存信息选 info 和真实记录编号；确认已有备选选 confirm_preview。
只有游客实际要求逐日排程或修改卡片，且有此表不能表达的行程约束/操作时，选 detailed：多日、出行日期、人数/交通限制、酒店、预算、具体景点预约窗口/停留时长、半日时长约束、区域硬限制、替换删站、指定攻略或撤回等。普通推荐、问地址、问开放时间、询问学习机会都选 info，可同时写入偏好。推荐附近哪里可以逛也选 info。勿将具体有空的起止时钟误作半日。无法绑定的硬性条件不准丢弃。
公共问题一项一个工具及补全主体的独立检索问句，彼此不要重复。不要根据一句“怎么走顺路、来得及吗”自行增设独立开放时间或定位问题；排程器会计算交通。介绍、场地、街区、社区访问和学习方式用主题知识库，纯经纬度或地图导航才用 location 且 query 只填地点名。明确每项事实的权属实体。根据近期对话消解'那里'、'刚才那些'。按兴趣在之前的候选里再推荐，是推荐任务，要把候选名称、兴趣、地理范围带入工具问句；只复述兴趣不能完成推荐。
明确交代今后推荐按某兴趣，是授权持久保存；仅本次想去不存。并行提问不取消保存。facts 的 subject 用 self 或 self.mother 等已有关系，relation 用 likes/name/stays_at；quote 必须是包含对象和陈述的本轮原文。纠正旧值用 set，新增喜好用 add，删除指定值用 remove。只读不得写。所有输出数组即使为空也要给出。"""
def clock_value(value,quote):
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",value):
        raise ValueError("钟点格式无效")
    h,m=map(int,value.split(":"))
    for _,_,literal in clocks(quote):
        a,b=map(int,literal.split(":"))
        if m==b and (h==a or a<12 and h==a+12):
            return h*60+m
    raise ValueError("钟点缺少原文依据")

def interpret_turn(model,q,state,validate):
    records=evidence(state)
    fields=obj({"field":enum(FIELDS),"value":STRING,"quote":STRING})
    job=obj({"name":enum([*TOOLS,"location"]),"query":STRING,"所求答案类型":STRING,"owner":enum(["数命社区场地及其运营","SAIG竞赛及参赛事务","其他主体"]),
             "此前供选择的地点":arr(STRING)})
    fact=obj({"subject":STRING,"relation":enum(["likes","name","stays_at"]),"object":STRING,
              "quote":STRING,"op":enum(["add","set","remove"])})
    properties={"outputs":arr(STRING),"mode":enum(MODES),"fields":arr(fields),"jobs":arr(job),"facts":arr(fact),
                "reads":arr(STRING),"needs_card":{"type":"boolean"}}
    if state.get("options"):
        properties["option_refs"]=arr(enum(state["options"]))
    schema=obj(properties)
    context={"本轮":q,"近期问答":state["turns"][-3:],"正式行程与资料记录":records,
             "人物及关系":state["facts"],"有备选":bool(state.get("pending_days")),"可规划地点":list(PLACES)}
    context["已交付的备选行程"]={k:v["title"] for k,v in state.get("options",{}).items()}
    frame=model.ask(INSTRUCTION+" 优先识别交付物：要求分别交付多套行程、独立成品、对成果作比较，或指向已交付的备选行程做查看/修改/选择，都选 compose，其他数组留空。"
                    "outputs 给每份可单独交付和验收的成品取一个不同的短名称。一张多日卡或其上的数项限制只列一份；同一地点几个属性可合为一份资料答复。"
                    "两个不同版本各是一份，另行要求的对比是第三份。若有 option_refs 只为本轮确实引用的已交付选项填编号。"
                    "若限定从此前推荐中选择，在该提问的“此前供选择的地点”逐字列全上一次回答给出的候选地点；无此范围给空数组。",
                    context,1200,schema)
    if (frame["mode"]=="compose" or len({v.strip() for v in frame["outputs"] if v.strip()})>1
            or frame.get("option_refs")
            or (frame["mode"] in ("edit","preview") and state.get("options") and not state["days"])
            or (frame["mode"]=="confirm_preview" and state.get("options") and not state.get("pending_days"))):
        return {"mode":"compose"}
    if frame["facts"] or frame["mode"] in ("plan","edit","preview"):
        # Resolve coupled changes together, before any write. No per-clause review loop.
        checked=model.ask("只核对授权和遗漏字段。以本轮原话为准：直接委托修改已买票/已晚点的约定属于现在更新；"
            "试算、问如果怎样、先看看才属于展示备选。新建行程及普通提问另选。补正只列漏项或需纠正的字段，不用重抄正确的。"
            "游览前已经身处的地点是 origin。later 表示推迟；earlier 表示提前。独立列出游客本轮明确授权修改的时间角色："
            "游客几点动身才选 start，接人或离开截止时间选 end。列车到点变化不等于游客也晚出门。"
            "只提一个想去的地方不等于明确限制游览总数。若游客要求在原约定上推迟或提早，从原话摘出变化时长，绑定它改变的那个约定。保留的提前量不是平移。"
            "只有明确试算或暂不采纳时才摘录试排原话。普通请你安排、怎么走、来得及吗等均无试排原话。"
            "另判断是否委托保留个人资料供以后使用，仅提供本趟住处不算。",
            {"原话":q,"提议":frame,"已有记录":records},620,obj({"本轮授权":enum(["现在更新已排行程","展示备选再决定","新建行程","其他"]),
                "约定平移":arr(obj({"改变的约定":enum(["游客从起点出门","游客到终点办事或接送"]),"方向":enum(["推迟","提早"]),"变动时长原文":STRING})),
                "明确限制游览总数":{"type":"boolean"},"试排原话":STRING,
                "委托长期记忆的原文":STRING,"补正字段":arr(fields)}))
        by_action={"现在更新已排行程":"edit","展示备选再决定":"preview","新建行程":"plan"}
        if frame["mode"] in ("plan","edit","preview") and checked["本轮授权"] in by_action:
            frame["mode"]=by_action[checked["本轮授权"]]
        hold=checked["试排原话"].strip()
        if frame["mode"]=="preview" and not state["days"] and (not hold or hold not in q):
            frame["mode"]="plan"
        for change in checked["补正字段"]:
            field=change["field"]
            same_role={field}
            if field.endswith(("_start","_end")):
                suffix=field.split("_")[1]
                same_role.update([suffix,"earlier_"+suffix,"later_"+suffix])
            if field!="must":frame["fields"]=[r for r in frame["fields"] if r["field"] not in same_role]
            if change not in frame["fields"]:frame["fields"].append(change)
        moves=[]
        for move in checked["约定平移"]:
            quote=move["变动时长原文"].strip()
            values=durations(quote)
            if state["days"] and quote and quote in q and len(values)==1:
                role="start" if move["改变的约定"]=="游客从起点出门" else "end"
                direction="later" if move["方向"]=="推迟" else "earlier"
                moves.append({"field":f"{direction}_{role}","value":str(values[0]),"quote":quote})
        if moves:
            frame["fields"]=[row for row in frame["fields"] if row["field"] in FIELDS[:5]+("must","max_stops")
                             and (row["field"] not in ("start","end") or clocks(row["quote"]))]
            frame["fields"].extend(moves)
        if not checked["明确限制游览总数"]:
            frame["fields"]=[row for row in frame["fields"] if row["field"]!="max_stops"]
        authorization=checked["委托长期记忆的原文"].strip()
        if not authorization or authorization not in q:frame["facts"]=[]
    for job in frame["jobs"]:
        prior=state["turns"][-1]["answer"] if state["turns"] else ""
        job["candidates"]=[n for n in job.pop("此前供选择的地点") if n and n in prior]
        if job["candidates"]:
            job["candidates"]=state["turns"][-1].get("offered_places") or job["candidates"]
            job["context_sources"]=state["turns"][-1].get("sources",[])
            job["query"]=q+" 可选地点："+"、".join(job["candidates"])+"。游客已知喜好："+"、".join(
                f["object"] for f in state["facts"] if f["subject"]=="self" and f["relation"]=="likes")
        owner = job.pop("owner")
        if owner=="SAIG竞赛及参赛事务":
            job["name"]="saig"
        elif owner=="数命社区场地及其运营" and job["name"]!="location":
            job["name"]="community"
    mode=frame["mode"]
    with timed("contract_compiled") as event:
        event.update(mode=mode,needs_existing=frame["needs_card"],fields=[r["field"] for r in frame["fields"]],
                     jobs=[j["name"] for j in frame["jobs"]],fact_count=len(frame["facts"]))
    target=None
    if mode in ("edit","preview") and len(state["days"])>1:
        # A time-only change to one named day of a multi-day trip stays on this path; anything wider goes to the planner.
        refs=list(dict.fromkeys(str(number(n)) for n in re.findall(rf"第({NUM})[天日]",q)))
        timing={"start","end","later_start","earlier_start","later_end","earlier_end","buffer"}
        if len(refs)!=1 or refs[0] not in state["days"] or frame["jobs"] or not frame["fields"] \
                or any(r["field"] not in timing for r in frame["fields"]):
            return None
        target=refs[0]
    if mode=="detailed":
        return None
    relative=any(r["field"].startswith(("later_","earlier_")) for r in frame["fields"])
    missing_card=(relative or mode in ("edit","keep") or (mode=="info" and frame["needs_card"] and not frame["jobs"])) and not state["days"]
    spec={"mode":mode,"days":[],"facts":frame["facts"],"tools":frame["jobs"],"records":[],
          "reads":[],"question":"","batch":True}
    if missing_card:
        spec.update(mode="info",question="当前还没有已确认的行程卡，无法读取或修改原来的安排。")
        return spec
    for key in dict.fromkeys(frame["reads"]):
        if key in records:spec["records"].append((key,records[key]))
    if mode=="info" and frame["needs_card"] and not spec["records"] and state["days"]:
        spec["reads"]=[q]
    for f in frame["facts"]:
        if (not f["object"] or f["object"] not in f["quote"] or f["quote"] not in q
                or not re.fullmatch(r"self(?:\.[a-z_]+)*",f["subject"])):
            return None
    if mode=="keep":
        spec.update(mode="info",question="沿用当前已确认的行程。")
    if mode not in ("plan","edit","preview"):
        return None if frame["fields"] else spec
    if mode=="plan" and state["days"]:return None
    old=(state["days"][target] if target else next(iter(state["days"].values()),{})) if mode!="plan" else {}
    op={"day":int(target or next(iter(state["days"]),1)) if old else 1,"query":q,
        "mobility":deepcopy(old.get("contract",{}).get("mobility",{"rules":[]})),"set":{}}
    for row in frame["fields"]:
        k,v,quote=row["field"],row["value"],row["quote"]
        if not quote or quote not in q:return None
        if k in ("origin","destination","must"):
            if v not in PLACES or v not in quote:return None
            if k=="must":
                op.setdefault("require",[]).append(v)
                continue
        elif k in ("start","end"):
            try:
                v=clock_value(v,quote)
            except ValueError:
                return None
            previous=old.get("contract",{}).get(k)
            if previous is not None and v<720 and previous==v+720:v=previous
        elif k.startswith(("later_","earlier_")):
            direction,k=k.split("_")
            if not v.isdecimal() or not old or int(v) not in durations(quote):return None
            v=old["contract"][k]+(int(v) if direction=="later" else -int(v))
        elif k=="buffer":
            v=int(v)
            if v and v not in durations(quote):return None
        elif k=="max_stops":
            v=int(v)
            if v!=len(set(op.get("require",[]))) and v not in [number(s) for s in re.findall(NUM,quote)]:
                # A count may be derived from a single explicitly exclusive list, even if must follows it.
                if v!=len({r["value"] for r in frame["fields"] if r["field"]=="must"}):return None
        if k in op["set"] and op["set"][k]!=v:return None
        op["set"][k]=v
    if mode!="plan" and not (op["set"] or op.get("require")):return None
    if mode in ("edit","preview") and old.get("order"):
        # A pure time change keeps every confirmed stop; the scheduler reports a conflict instead of silently dropping one.
        op["add"]=list(old["order"])
    if not old and not op["set"] and not op.get("require"):return None
    if not old and clocks(q) and not ({"start","end"} & op["set"].keys()):return None
    validate(op)
    spec["days"]=[op]
    return spec
