"""Translate model-assigned roles into evidence-bound day operations."""
import re
from quantities import clocks, durations, number, NUM
from places import PLACES
from semantics import compile_day, obj, enum, arr, STRING

ACTIONS={
    "开始游览时刻":"start","结束游览或到达截止时刻":"end","集合出发地点":"origin","必须抵达的终点":"destination",
    "车站提前量分钟":"buffer","全日最多站数":"max_stops","全日时长上限分钟":"max_minutes",
    "站内停留分钟":"duration","站内游览时间窗":"window","限定区域":"region",
    "必须游览":"require","取消必去资格":"unrequire","长期排除游览":"exclude","解除长期排除":"allow",
    "本次加站":"add","本次移除游览":"remove","在原位置换站":"replace","保护全部原站":"keep_all"}
FIELDS=obj({"原文片段编号":{"type":"integer"},"动作":enum(ACTIONS),"站点对象或空":STRING,"新值":STRING})
FRAME=obj({"理解":STRING,"操作":{**arr(FIELDS),"maxItems":18}})
CLOCK_FIELDS={"出发地":"origin","出发时间":"start","最终必须到达的地点":"destination","最晚结束时间":"end"}

def travel_roles(model,text,items,spans,existing):
    result={}
    names=[n for n in PLACES if n in text]
    # Recognize literal entities, then bind each occurrence in its own clause. One name can
    # be both a hotel origin and a visit that is being removed.
    mentions=model.ask("抽取这句话出现的具体地点专名，逐字抄录，没有就给空数组。",text,130,
        obj({"地点":arr(STRING)}))["地点"]
    names=list(dict.fromkeys(names+[n for n in mentions if n and n in text]))
    for index,span in enumerate(spans,1):
        for name in names:
            if name not in span:continue
            if any(name!=other and name in other and other in span and name not in span.replace(other,"") for other in names):continue
            mark=span.replace(name,"【"+name+"】",1)
            role=model.ask("从游客当天移动的角度判断标记地点。旅客住处/集合出门处是起点；去接人、赶乘从该站开出的交通工具，车站都是游客必须抵达的终点。只有游览或区域描述选游览/其他。",
                {"标记短句":mark,"整句":text},110,obj({"动词依据":STRING,"角色":enum(["起点集合","要求到达","游览","其他"])}))["角色"]
            field={"起点集合":"origin","要求到达":"destination"}.get(role)
            if field:
                roles_here={ACTIONS[i["动作"]] for i in items if i["原文片段编号"]==index
                            and name in (i["站点对象或空"],i["新值"])}
                visit_only=roles_here & {"require","unrequire","add","remove","exclude","allow","replace","duration","window"}
                if visit_only and field not in roles_here and not any(ACTIONS[i["动作"]]=="buffer" for i in items):
                    # An instruction about visiting a stop does not by itself appoint it as an endpoint.
                    continue
                if name not in PLACES:
                    usage=model.ask("引号中的地名是用来描述路线的游玩片区/主题，还是被明确约定为必须抵达或出发的具体位置？"
                        "按短句的动词和完整语境判断。",{"原话":text,"待确认的短句":mark},80,
                        obj({"用途":enum(["游玩范围或描述","已指定的行程端点"])}))
                    if usage["用途"]!="已指定的行程端点":continue
                    raise ValueError("地点“"+name+"”未收录，无法核实要求。")
                if field=="destination" and any(ACTIONS[i["动作"]] in ("require","add") and name in (i["新值"],i["站点对象或空"]) for i in items):
                    final=model.ask("这句话除了要求看这个景点，还明确要求当天行程在这里结束吗？",
                        {"景点":name,"原话":text},40,obj({"也明确指定为终点":{"type":"boolean"}}))
                    if not final["也明确指定为终点"]:continue
                if field in result and result[field]!=name:
                    named=list(dict.fromkeys([result[field],name]))
                    picked=model.ask("两段解析提到了同一角色的不同地点。选择原话真正指定的那个；如确实互相矛盾无法确定选待确认。",
                        {"角色":"出发地点" if field=="origin" else "最终到达地点","候选":named,"原话":text},70,
                        obj({"地点":enum([*named,"待确认"])}))["地点"]
                    if picked=="待确认":raise ValueError("同一天的行程端点有两个候选，请确认"+"或".join(named))
                    name=picked
                result[field]=name
        local_clocks=clocks(span)
        # A time interval with a day subject and no visit object is the day's availability.
        if len(local_clocks)==2 and not any(n in span for n in names):
            visit_window=any(ACTIONS[i["动作"]]=="window" and i["站点对象或空"] in PLACES
                and i["原文片段编号"]==index for i in items)
            if not visit_window:
                result.update(start=local_clocks[0][2],end=local_clocks[1][2])
                continue
        for a,b,value in clocks(span):
            mark=span[:a]+"【"+span[a:b]+"】"+span[b:]
            choice=model.ask("方括号里的这个钟点约束什么动作？起止范围中前者是出发后者是结束。"
                "整趟行程须在某时前到达某地属于结束/到达截止。只限制某一站的游览时间属于单站。不得推断没说的出发钟点。",
                {"上下文":text,"只判断此处":mark},100,obj({"绑定的动作":enum(["开始一天的行程","结束或最迟抵达","单站游览窗口","无关时间"])}))
            field={"开始一天的行程":"start","结束或最迟抵达":"end"}.get(choice["绑定的动作"])
            if field:
                literal=span[a:b].strip()
                # Spoken clocks without a period can inherit the existing appointment.
                h,m=map(int,value.split(":"))
                if h<12 and not re.search(r"凌晨|清晨|早上|上午|中午|下午|傍晚|晚上|[:：]",literal):
                    options=[value,f"{h+12:02d}:{m:02d}"]
                    prior=existing.get(field)
                    value=model.ask("把省略上午下午的钟点还原为24小时，依据全句与原先已确认时段。更改目的时原约定半天仍适用。",
                        {"原话":text,"标记":mark,"字段":field,"原约定":f"{prior//60:02d}:{prior%60:02d}" if prior is not None else None},
                        55,obj({"时刻":enum(options)}))["时刻"]
                result[field]=value
    terminal=model.ask("按旅行的先后顺序判断。若有发生在游览之后、游客必须赶到的乘车或接送约定，逐字摘出含地点的原文。"
        "游览前碰头集合是出发，游览结束的时限只是时限，两者均不授权添加一个游览后的目的地。",
        {"原文":text,"此前逐项绑定的字段":result},110,obj({"游览后的约定原文":STRING,"行程末端事件":enum(["赶乘","接送或会合","无"])}))
    event=terminal["行程末端事件"]
    witness=terminal["游览后的约定原文"].strip()
    if not witness or witness not in text:event="无"
    if event!="无" and result.get("origin") and result["origin"] in witness:
        timing=model.ask("标记的这次约定发生在开始游览前，还是在游览之后？",
            {"原话":text,"待核约定":witness},45,obj({"相对游览":enum(["之前","之后","没有说清"])}))
        if timing["相对游览"]!="之后":event="无"
    if event!="无":
        for k in ("start","end","destination","origin"):
            result.pop(k,None)
        locations=list(dict.fromkeys(names+[n for n in (existing.get("origin"),existing.get("destination")) if n]))
        for key,purpose in (("origin","游客当天从哪儿出门？居住地可作为出门地点。"),("destination","游客赶车/接送/会合必须抵达哪儿？交通工具离开的站对于游客是目的地。")):
            chosen=model.ask(purpose+"只选游客实际指定或本次重申的地点，无则选未指定。",text,55,
                obj({"地点":enum(["未指定",*locations])}))["地点"]
            if chosen!="未指定":
                if chosen not in PLACES:raise ValueError("地点“"+chosen+"”未收录，无法核实要求。")
                result[key]=chosen
        if result.get("origin") and result["origin"]==result.get("destination"):
            round_trip=model.ask("游客是否明确要求从这个地方开始全天行程又在同一地结束？只要求去那里办事不构成往返。",
                {"地点":result["origin"],"原话":text},45,obj({"明确往返":{"type":"boolean"}}))["明确往返"]
            if not round_trip:result.pop("origin")
        witnesses={}
        for key,meaning in (("start","游客自己开始游玩、从住处动身的时刻。交通工具发车、抵达目的地、接人时刻全都不能用作游客出发时刻。"),
                            ("end","到达终点或乘车/接人/会合的截止时刻，不要提前扣除提前量。")):
            timed=[span for span in spans if clocks(span)]
            if not timed:continue
            selected=model.ask("选择实际明确指定此约束的原话，否则选未指定："+meaning,
                {"所问字段":key,"整句":text,"可选时间片段":timed},70,obj({"直接依据":enum(["未指定",*timed])}))["直接依据"]
            if selected=="未指定":continue
            witnesses[key]=selected
            possible=[]
            for a,b,value in clocks(selected):
                possible.append(value)
                h,m=map(int,value.split(":"))
                if h<12 and not re.search(r"上午|凌晨|清晨|早上|中午|下午|傍晚|晚上|[:：]",selected[a:b]):
                    possible.append(f"{h+12:02d}:{m:02d}")
            if len(possible)==1:value=possible[0]
            else:
                prior=existing.get(key)
                value=model.ask("结合本轮上下文与原有约定，选择该字段所指的24小时钟点。",
                    {"字段含义":meaning,"整句":text,"片段":selected,"原时刻":f"{prior//60:02d}:{prior%60:02d}" if prior is not None else None},50,
                    obj({"时间":enum(dict.fromkeys(possible))}))["时间"]
            result[key]=value
        if witnesses.get("end") and witnesses.get("start")==witnesses["end"] and len(clocks(witnesses["end"]))==1:
            # The single terminal appointment cannot independently authorize a new departure.
            result.pop("start",None)
        buffers=[span for span in spans if durations(span)]
        action=model.ask("本次对在终点预留的提前量有什么要求？",{"原话":text,"事件":event},55,
            obj({"要求":enum(["明确无需或取消提前量","规定了具体提前量","没有更改提前量"])}))["要求"]
        if action=="明确无需或取消提前量":result["buffer"]=0
        if action=="规定了具体提前量" and buffers:
            selected=model.ask("选择描述抵达目的地应提前多久的片段。",text,50,obj({"依据":enum(buffers)}))["依据"]
            amounts=durations(selected)
            if len(amounts)==1:result["buffer"]=amounts[0]
    if not clocks(text) and existing:
        for i in items:
            field=ACTIONS[i["动作"]]
            if field not in ("start","end"):continue
            delta=model.ask("将相对于原约定的时间变更表示成分钟，延后为正、提前为负，没有提出相对变更用0。",{"游客":text,"时间项":i["动作"]},60,obj({"分钟":{"type":"integer"}}))["分钟"]
            if delta:
                value=existing[field]+delta
                if not 0<=value<1440: raise ValueError("调整后的钟点超出当天")
                result[field]=f"{value//60:02d}:{value%60:02d}"
    return result

PROMPT="""你是旅行订单修改员。只抄录这位游客明确指定的事项，不代做路线设计。使用已有行程区分集合、游览与离开的地点。
先简短概括游客想产生的差异，再逐项记录。原文编号来自输入，可重复。游览持续时间换算成整数分钟，钟点写24小时HH:MM，访问窗口写HH:MM-HH:MM。
时间点只绑定它修饰的动作。到目的地接人写终点和截止时间，发车另有进站提前量。已有约定不重复写。不把参观最后一站推断为返程终点。
当天想看/一定要去列为必须游览，取消资格和从本次移除可同时发生。保留其他顺序是默认行为；只有禁止删任何原站才记录保护全部原站。
只有游客明确要求未来也禁止时才长期排除。当次删站只影响本次。删除起点的游览身份不动出发位置。
对象栏是执行动作的地点（或原站序里的序号），每天整体的钟点/上限不填对象。增删、必去、起终点用对象栏写地点。
替换时对象是旧站，新值是指定新站；由接待员代选的填写“待选”。仅给出兴趣不要自行挑站。目的地不在目录也照实抄写，勿用相近地名代替。
数值必须能由对应原文推出，不用把起止时刻之差另计作总预算。以目标日为范围；其他天的事项不写。"""

def day_patch(model,q,day,card,validate,mode=None):
    spans=[v.strip() for v in re.split(r"[，。；！？!?;,]",q) if v.strip()]
    order=card.get("order",[])
    context={"工作版本":"仅在备选副本上执行假设改动，原卡不动" if mode=="preview" else "当前行程","目标日":day,"原站序":dict(enumerate(order,1)),
             "已有必去":card.get("contract",{}).get("must",[]),"句子编号":dict(enumerate(spans,1)),"游客原话":q}
    for attempt in range(3):
        raw=model.ask(PROMPT,context,900,FRAME)
        try:
            changes=[]
            protect=False
            travel=not card or bool(clocks(q)) or any(ACTIONS[i["动作"]] in {*CLOCK_FIELDS.values(),"buffer"} for i in raw["操作"])
            roles=travel_roles(model,q,raw["操作"],spans,card.get("contract",{})) if travel else {}
            for item in raw["操作"]:
                index=item["原文片段编号"]
                if not 1<=index<=len(spans): raise ValueError("原文片段编号越界")
                field=ACTIONS[item["动作"]]
                if field in CLOCK_FIELDS.values():continue
                target=item["站点对象或空"].strip()
                value=item["新值"].strip()
                if field=="duration" and not durations(spans[index-1]):
                    candidates=[i for i,s in enumerate(spans,1) if durations(s)]
                    direct=[i for i in candidates if target and target in spans[i-1]]
                    if len(direct)==1:index=direct[0]
                    elif len(candidates)==1:index=candidates[0]
                    else:raise ValueError("指定站点的停留时长缺少可定位的原文")
                if field=="region":
                    from planning import REGIONS
                    area=model.ask("将原文里的地理限制与系统支持的片区对齐。只写兴趣、主题或没有指定片区选未限定。"
                        "明确要求目录外的地理片区选其他片区。",{"原句":spans[index-1],"目标":target,"值":value},70,
                        obj({"片区":enum([*REGIONS,"未限定","其他片区"])}))["片区"]
                    if area=="未限定":continue
                    if area=="其他片区":return None,"无法核实该片区："+spans[index-1]
                    value=area
                if target.isdecimal() and 1<=int(target)<=len(order):target=order[int(target)-1]
                if field=="keep_all":
                    protect=protect or model.ask("这一条本身是否明确要求绝对不删任何一个原站？仅保持顺序、其余时间或条件照旧不构成禁止删站。",
                        {"依据":spans[index-1]},35,obj({"explicit":{"type":"boolean"}}))["explicit"]
                    continue
                if field in ("origin","destination","require","unrequire","exclude","allow","remove","add"):
                    name=target if target in PLACES else value if value in PLACES else target or value
                    if name not in PLACES:
                        entity=model.ask("候选词是游客明确提到的地理地点名称吗？排程指令、时间、偏好和确认动作不是地点。"
                            "只在原话确实指认该地点时选择地点。",
                            {"候选词":name,"本轮原话":q},55,obj({"词义":enum(["地点专名","非地点或无依据"])}))
                        if name not in q or entity["词义"]!="地点专名":continue
                        return None,"地点“"+name+"”未收录，无法核实这项行程要求。"
                    value=name
                if field=="window" and not target and len(clocks(spans[index-1]))==2:
                    continue
                if field=="max_minutes" and not durations(spans[index-1]) and "半天" not in spans[index-1]:
                    continue
                if field in ("window","duration","replace"):
                    if target not in PLACES or (order and target not in order):
                        raise ValueError("指定站点没有绑定到行程对象")
                if order and field in ("remove","exclude","unrequire","replace","duration","window"):
                    bound=target if field in ("replace","duration","window") else value
                    if bound not in q:
                        positions=[number(m)-1 for m in re.findall(rf"第({NUM})(?:个)?(?:游览)?站",q)]
                        if "最后一站" in q or "末站" in q:positions.append(len(order)-1)
                        if "首站" in q:positions.append(0)
                        if bound not in [order[p] for p in positions if 0<=p<len(order)]:
                            return None,"你指的是哪一站？本日依次是"+"、".join(order)+"。"
                if field=="replace" and (value not in PLACES or value not in q):
                    value="从攻略选取"
                if field=="exclude":
                    scope=model.ask("游客真的要求在未来每次重排都禁止游览这个站吗？需要区分否定、转述、仅此一次和持续禁用。"
                        "请根据整句最后的意愿作判断。",{"对象":value,"原话":q},100,
                        obj({"实际有效期":enum(["明确要求今后一直禁用","只取消本次游览","没有授权排除"])}))["实际有效期"]
                    if scope=="没有授权排除":continue
                    if scope=="只取消本次游览":field="remove"
                if field in ("buffer","max_stops","max_minutes","duration"):
                    value=int(value.removesuffix("分钟").removesuffix("站").strip())
                if field in ("duration","max_minutes","buffer"):
                    amounts=durations(spans[index-1])
                    if len(amounts)==1:
                        value=amounts[0]
                    if field=="buffer":
                        policy=model.ask("游客对该提前量是在要求预留，还是取消/明确无需预留？",{"整句":q,"原句":spans[index-1]},
                            45,obj({"动作":enum(["需要预留","取消预留"])}))
                        if policy["动作"]=="取消预留":value=0
                changes.append(dict(field=field,value=value,target=target,quote=spans[index-1]))
            op=compile_day({"changes":changes,"query":q},day,q)
            existing=card.get("contract",{})
            if existing and roles and ("buffer" in roles or "destination" in roles):
                guarded=model.ask("逐字摘出游客明确点名要求沿用的字段。只从实际说要保持的原句选择；"
                    "不把其余照旧推成全部字段。对只试算的游客仍应在备选上执行所要求的变更。",
                    {"原句":q,"原卡上的值":existing,"本轮解释":roles,"可以保持的字段":{"origin":"从哪里出门","start":"几点出门","end":"最晚几点到","destination":"最终在哪里结束","buffer":"提前多久"}},
                    145,obj({"保留":arr(obj({"字段":enum(["origin","start","end","destination","buffer"]),"依据":STRING}))}))["保留"]
                for item in guarded:
                    field=item["字段"]
                    if field not in roles or existing.get(field) is None or not item["依据"].strip() or item["依据"] not in q:continue
                    binding=model.ask("判断引文的言语行为。只有明确要求保留此前原卡上的旧值时选沿用；"
                        "重申要赶哪班车、几点到、留多少分钟或说明新条件均选指定。泛指其他照旧选无关。",
                        {"引文":item["依据"],"整句":q,"字段":field,"原卡旧值":existing[field],"新解析":roles[field]},50,
                        obj({"行为":enum(["沿用旧值","本轮指定","无关"])}))["行为"]
                    if binding=="沿用旧值":roles.pop(field)
            op["set"].update(roles)
            for name in op.get("unrequire",[]):
                if name in order and name not in existing.get("must",[]) and name not in op.get("remove",[]):
                    visit=model.ask("根据游客原话，该地点是否还应作为这一次的游览站？集合地点不一定是游览站。",
                        {"待确认地点":name,"本轮":q},45,obj({"本次仍游览":{"type":"boolean"}}))
                    if not visit["本次仍游览"]:op.setdefault("remove",[]).append(name)
            for field,stored in (("require","must"),("exclude","exclude")):
                if field in op: op[field]=[n for n in op[field] if n not in existing.get(stored,[])]
            for field,stored in (("unrequire","must"),("allow","exclude")):
                if field in op:op[field]=[n for n in op[field] if n in existing.get(stored,[])]
            for field,value in list(op["set"].items()):
                prior=existing.get(field)
                if field in ("start","end") and isinstance(value,str):
                    from datetime import time
                    clock=time.fromisoformat(value)
                    value=clock.hour*60+clock.minute
                if value==prior: del op["set"][field]
            for bounds in op["set"].get("windows",{}).values():
                if len(bounds)!=2 or bounds[0]>=bounds[1]:
                    raise ValueError("单站时间窗必须有独立的开始和结束，整体到达截止不应建立景点窗口。")
            if protect:
                removed=set(op.get("remove",[]))|set(op.get("exclude",[]))|{r["old"] for r in op.get("replacements",[])}
                op["add"]=list(dict.fromkeys(op.get("add",[])+[n for n in order if n not in removed]))
            cap=op["set"].get("max_stops",card.get("contract",{}).get("max_stops",12))
            if not card and op.get("require") and "max_stops" not in op["set"]:
                exclusivity=model.ask("这些必去游览点是整天仅允许的游览集合，还是可以搭配其他站？"
                    "只有原话明确禁止安排其他游览点才填写禁止扩展的逐字原句；仅限片区、限制时段或单个地点必须去均填空。",
                    {"游客原话":q,"已确认必去":op["require"]},90,obj({"禁止其他游览站的原句":STRING}))
                quote=exclusivity["禁止其他游览站的原句"].strip()
                if quote and quote in q:
                    meaning=model.ask("只判断这句是否禁止加入任何别的游览点。只提区域、交通、体力或必去不算。",
                        quote,35,obj({"禁止增站":{"type":"boolean"}}))
                    if meaning["禁止增站"]:
                        cap=len(set(op["require"]+op.get("add",[])))
                        op["set"]["max_stops"]=cap
            if len(set(op.get("add",[])+op.get("require",[])))>cap:
                return None,f"条件冲突：需要保留 {len(set(op.get('add',[])+op.get('require',[])))} 站，但最多 {cap} 站。你希望放宽站数，还是允许删站？"
            if order and not (any(op.get(k) for k in ("set","require","exclude","allow","unrequire","replacements"))
                or set(op.get("remove",[]))&set(order) or set(op.get("add",[]))-set(order)):
                return None,""
            validate(op)
            return op,""
        except (TypeError,ValueError,KeyError) as err:
            if "未收录" in str(err):return None,str(err)
            context["待纠正"]={"原因":str(err),"上版":raw["操作"]}
    return None,"未能确认这项改动："+str(context["待纠正"]["原因"])


