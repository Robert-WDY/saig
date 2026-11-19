from copy import deepcopy
from uuid import uuid4
from knowledge import Knowledge, TOOLS, grounded, verify_statement
from model import Model
from places import PLACES, locate
from planning import Invalid, evaluate, guide_candidates, new_contract, solve, validate
from storage import Sessions
from diagnostics import timed
from trip_contract import GUIDES, CITY_SOURCE, settings, trip_review, rebind_overnights
from transport import LABEL
from planning import transport_cache

from semantics import arr, enum, interpret, obj, STRING

CHECK = """逐项比较用户原话、原会话与拟执行的结构化动作，检查是否漏掉明确的要求、对象/天数/约束绑定错误、将假设当确认、无依据地取消旧约束。若凭空添加目的地、景点、每个景点访问窗口、或错误转换时钟，一律返回false。
用户没要求的自由游览时段可用默认值；已有信息可引用。可在guide查询中表达软兴趣；硬约束必须可审核或列为unsupported。
同意时返回 {"ok":true,"reason":""}。否则返回 {"ok":false,"reason":"一句话指出字段错误"}。这里仅审核语义对应关系，时间算术由程序负责。即使两个时间相隔太短、行程不可行，只要准确记录用户所说条件，语义审核必须通过，交给排程器判断可行性。"""

def memory_view(state):
    return {"days":{k:{"contract":v["contract"],"order":v["order"],
                      "objects":[f"{k}/{name}" for name in v["order"]],**({"calendar_label":v["calendar_label"]} if "calendar_label" in v else {})}
                    for k,v in state["days"].items()},
            "objects":{k:v["audit"]["stops"] for k,v in state["days"].items()},
            "versions":{"有未确认预览":bool(state.get("pending_days")),"可撤销":bool(state.get("past_days"))},
            "facts":state["facts"],"recent":state["turns"][-6:]}


def apply_facts(state, facts, sentence):
    for fact in facts:
        fields=("subject","relation","object","quote")
        if not isinstance(fact,dict) or any(not isinstance(fact.get(k),str) or not fact[k].strip() for k in fields):
            raise Invalid("记忆缺少人物、关系、对象或出处")
        if fact["quote"] not in sentence:
            raise Invalid("记忆依据未出现在用户原话")
        if fact["object"] not in fact["quote"]:
            raise Invalid("记忆值没有绑定到游客的原句")
        key=(fact["subject"],fact["relation"])
        op=fact.get("op","set")
        if op not in ("add","remove","set"):
            raise Invalid("未知记忆修改方式")
        state["facts"]=[x for x in state["facts"] if (x["subject"],x["relation"])!=key
                        or (op!="set" and x["object"]!=fact["object"])]
        if op!="remove":
            entry={k:fact[k] for k in fields}
            entry["object_ref"]="place/"+fact["object"] if fact["object"] in PLACES else fact["object"]
            state["facts"].append(entry)


def apply_constraints(old, op):
    c={**new_contract(),**deepcopy(old)}
    if "mobility" in op:c["mobility"]=deepcopy(op["mobility"])
    changes=op.get("set",{})
    if not isinstance(changes,dict) or set(changes)-{"start","end","origin","destination","buffer","durations","windows","regions","max_stops","max_minutes"}:
        raise Invalid("存在无法审核的约束字段")
    def clock(v):
        if isinstance(v,str):
            import datetime
            t=datetime.time.fromisoformat(v)
            return 60*t.hour+t.minute
        return v
    for k,v in changes.items():
        if k in ("start","end"):
            v=clock(v)
        if k=="windows":
            v={name:[clock(a),clock(b)] for name,(a,b) in v.items()}
        if k in ("durations","windows"):
            c[k].update(v)
        else:
            c[k]=v
    for key,plus,minus in [("must","require","unrequire"),("exclude","exclude","allow")]:
        c[key]=[n for n in c[key] if n not in op.get(minus,[])]
        c[key]=list(dict.fromkeys(c[key]+op.get(plus,[])))
    for key in ("require","unrequire","exclude","allow","add","remove"):
        if not isinstance(op.get(key,[]),list) or any(n not in PLACES for n in op.get(key,[])):
            raise Invalid("站点引用不在已核实目录")
    validate(c)
    return c


def hhmm(t):
    return f"{t//60:02d}:{t%60:02d}"


class Agent:
    def __init__(self,db,model=None,kb=None):
        self.store=Sessions(db)
        self.model=model or Model()
        self.kb=kb or Knowledge()

    @timed("understand")
    def understand(self,q,state):
        from visitor_turn import interpret_turn
        def validate_compact(op):
            day=state["days"].get(str(op["day"]))
            apply_constraints(day["contract"] if day else new_contract(),op)
        with timed("turn_contract"):
            try:
                compact=interpret_turn(self.model,q,state,validate_compact)
            except Invalid:
                compact=None
        if compact is not None:return compact
        with timed("detailed_contract"):
            return self.understand_detailed(q,state)

    def understand_detailed(self,q,state):
        rejected=[]
        def validate_op(op):
            day=state["days"].get(str(op["day"]))
            try:
                apply_constraints(day["contract"] if day else new_contract(),op)
            except Invalid as exc:
                rejected.append({"operation":deepcopy(op),"reason":str(exc)})
                raise
        spec=interpret(self.model,q,memory_view(state),CHECK,validate_op)
        if spec.get("facts") and not spec.get("tools"):
            import re
            clauses=[s.strip() for s in re.split(r"[，,。！？!?；;]",q) if s.strip()]
            if len(clauses)>1:
                outstanding=self.model.ask("记录个人事实后，原文还明确向接待员询问哪些独立的公共知识？"
                    "每项选择实际提问的原文片段和对应工具。只陈述个人资料、读回或否定提问均返回空。"
                    "food 管早餐与饮食文化，wuhan 管城市地理历史，community 管场地运营，spu 管数命概念，saig 管赛事。",
                    clauses,225,obj({"待答":arr(obj({"原句":enum(clauses),"工具":enum([*TOOLS,"location"])}))}))
                for item in outstanding["待答"]:
                    spec.setdefault("tools",[]).append({"name":item["工具"],"query":item["原句"],"source_query":item["原句"]})
        if spec.get("facts") and spec.get("tools") and not spec.get("write_authorization"):
            # A public answer can use context without committing it to the visitor profile.
            command=self.model.ask("游客同时在问公开信息。另有明确要求接待员为以后保存、更新或删除个人资料吗？"
                "逐字摘出指令中表示记忆操作的动词；没有这样的动词就填空串。不要摘游客自己正在做的事或提问动词。",
                q,45,obj({"记忆指令动词":STRING}))["记忆指令动词"].strip()
            permitted=False
            if command and command in q:
                meaning=self.model.ask("只判断这段措辞表达的动作。它是在委托保留、更正或删除记录，还是叙述本次工作、询问或核对信息？",
                    {"指令原词":command,"完整原话":q},65,obj({"动作":enum(["另行写入或维护记录","其他动作"])}))["动作"]
                permitted=meaning=="另行写入或维护记录"
            if not permitted:spec["facts"]=[]
        if spec.get("facts"):
            candidates={str(i):fact for i,fact in enumerate(spec["facts"],1)}
            permitted=self.model.ask("逐项审核人物资料写入。所选操作必须是游客原话对该人、该关系和该值的明确陈述或纠正、撤销。"
                "检查是谁的观点，以及是否明确禁止存为偏好。引述第三方观点不能推断为说话者喜好。只选确有依据的编号。",
                {"完整原话":q,"拟写操作":candidates},75,obj({"批准编号":arr(enum(candidates))}))["批准编号"]
            spec["facts"]=[fact for key,fact in candidates.items() if key in permitted]
        if state["facts"] and spec["mode"]=="info":
            records={str(i):f for i,f in enumerate(state["facts"])}
            changes=self.model.ask("对照已存记录，识别本轮明确指出某一旧值错误并给出替代值的纠正。"
                "询问、假设、转述、保持原样、禁止更改均返回空。人物指代结合近期对话。"
                "选择旧记录编号，并逐字摘出新值与含新值的原文。只修改点名的一条记录。",
                {"本轮":q,"记录":records,"最近对话":state["turns"][-2:]},165,
                obj({"纠正":arr(obj({"旧记录":enum(records),"新值":STRING,"依据":STRING}))}))["纠正"]
            for change in changes:
                old=records[change["旧记录"]]
                val,quote=change["新值"].strip(),change["依据"].strip()
                key=(old["subject"],old["relation"])
                if not val or val==old["object"] or val not in quote or quote not in q:continue
                if sum((f["subject"],f["relation"])==key for f in records.values())!=1:continue
                facts=spec.setdefault("facts",[])
                facts[:]=[f for f in facts if (f["subject"],f["relation"])!=key]
                facts.append({"subject":key[0],"relation":key[1],"object":val,"quote":quote,"op":"set"})
        if rejected:spec["rejected_constraints"]=rejected
        return spec

    def tool(self,name,query,k=5):
        if name=="location":
            return locate(query)
        if name not in TOOLS:
            raise Invalid("未注册工具："+name)
        return self.kb.search(query,TOOLS[name],k)

    @timed("consult")
    def consult(self,jobs,trace):
        parts,citations=[],[]
        for job in jobs:
            name,query=job["name"],job["query"]
            if any(t.get("step")=="answered_question" and t["tool_name"]==name and t["query"]==query for t in trace):
                continue
            if name=="location":
                locations=self.tool(name,query)
                trace.append({"tool":name,"result":locations})
                for p in locations["catalog"]:
                    parts.append(directions(p))
                parts.extend(p["address"]+"（GCJ-02 "+p["gcj02"]+"）" for p in locations["geocodes"])
                if locations.get("notice"):
                    parts.append(locations["notice"])
                if not locations["catalog"] and not locations["geocodes"]:
                    rows=self.kb.search(query,k=6)
                    context=job.get("context_query",query)
                    contextual=self.kb.search(context+" "+query,k=8)
                    rows=list({row["id"]:row for row in [*contextual,*rows]}.values())
                    resolved=grounded(self.model,"仅回答位置：根据游客上下文辨认场所。能确认街区而无门牌时，给出街区。"
                                      +"游客原话："+context+"。待答位置："+query,rows)
                    if resolved["citations"]:
                        parts.append(resolved["answer"])
                        citations.extend(resolved["citations"])
                        trace.append({"step":"resolve_location_from_sources","sources":[c["id"] for c in resolved["citations"]]})
                    else:parts.append("位置工具未找到可确认的地点，请补充地名或地址。")
            else:
                rows=self.tool(name,query)
                if job.get("assertion"):
                    context_rows=self.kb.search(job["context_query"],k=5)
                    rows=list({r["id"]:r for r in [*context_rows,*rows]}.values())
                elif job.get("source_query"):
                    alternatives=self.kb.search(job["source_query"],k=5)
                    if alternatives and alternatives[0]["category"] not in TOOLS[name]:
                        pool={r["id"]:r for r in [*rows[:3],*alternatives]}
                        chosen=self.model.ask("核对工具分流。哪一段资料最能直接回答当前问题？没有直接支持选NONE。"
                            "参考独立检索提问补全指代，优先依据事实内容，不要只看机构或地名重合。",
                            {"资料":{k:v["text"][:300] for k,v in pool.items()},"独立提问":query,"游客原句":job["source_query"]},
                            80,obj({"证据":enum(["NONE",*pool])}))["证据"]
                        if chosen in pool and pool[chosen]["category"] not in TOOLS[name]:
                            category=pool[chosen]["category"]
                            if category in TOOLS:
                                trace.append({"step":"tool_reroute","from":name,"to":category,"evidence":chosen})
                                name=category
                                rows=self.tool(name,query)
                                rows=[pool[chosen],*[r for r in rows if r["id"]!=chosen]]
                trace.append({"tool":name,"query":query,"hits":[r["id"] for r in rows]})
                if job.get("assertion"):
                    result=verify_statement(self.model,job["assertion"],job["source_query"],rows)
                else:
                    result=grounded(self.model,query,rows,job.get("source_query"))
                parts.append(result["answer"])
                citations.extend(result["citations"])
                trace.append({"step":"answered_question","tool_name":name,"query":query,
                              "supported":result["supported"],"sources":[c["id"] for c in result["citations"]]})
                for url in dict.fromkeys(c["source"] for c in result["citations"] if c["id"]=="register"):
                    parts.append("官方报名入口："+url)
        return parts,citations

    @timed("schedule_day")
    def day(self,key,op,old,trace):
        c=apply_constraints(old["contract"] if old else new_contract(),op)
        prior=old["order"] if old else []
        trace.append({"step":"frozen_day","day":key,"before":old["contract"] if old else None,
                      "constraints":deepcopy(c),"prior_stops":list(prior)})
        available=min(c["end"]-c["start"],c["max_minutes"])-c["buffer"]
        required=sum(c["durations"].get(n,PLACES[n]["minutes"]) for n in set(c["must"])|set(op.get("add",[])))
        if required>available:
            detail=f"第{key}天最多可用{max(0,available)}分钟，必去站停留至少需要{required}分钟，转场还需另计。"
            trace.append({"day":key,"audit_error":detail})
            raise Invalid(detail)
        replacements=op.get("replacements",[])
        if any(r["old"] not in prior for r in replacements):
            raise Invalid("请指明原卡上要替换的具体站点。")
        query=op.get("query") or "武汉城市历史街区漫游"
        search=query+" "+" ".join(c["must"]+[c["origin"] or ""])
        retrieved=self.tool("guide",search,12)
        matches=guide_candidates(retrieved,c["must"])
        template=next((g for g in GUIDES if g["id"]==op.get("template")),None)
        if template and int(key)>len(template["days"]):template=None
        if not template and (not old or replacements) and matches:
            by_id={r["id"]:r for r in retrieved}
            options=[{"id":gid,"places":names,"excerpt":by_id[gid]["text"][:180]} for _,gid,names in matches[:6]]
            pick=self.model.ask("""按游客兴趣和已冻结条件选最合适的一条攻略，从它的places中选符合条件的站点。
输出 {id:实际攻略编号,order:[该攻略中拟采用的地点名]}。规划器另行加入必去点；不能修改约束。""",
                                {"request":query,"constraints":c,"guides":options},200)
            selected=next((o for o in options if o["id"]==pick.get("id")),None)
            names=pick.get("order")
            if selected and isinstance(names,list) and names and all(n in selected["places"] for n in names):
                matches.insert(0,(0,selected["id"],list(dict.fromkeys(names))))
        if template:
            source_order=template["days"][int(key)-1]
            matches.insert(0,(0,template["id"],source_order))
            if op.get("strict_template"):
                if set(source_order)&set(op.get("avoid",())):
                    raise Invalid("原攻略包含与其他日期重复的站点，请确认是否保留重复游览。")
                op={**op,"add":list(dict.fromkeys([*op.get("add",[]),*source_order]))}
                matches=matches[:1]
        if not matches and not prior and not c["must"] and not op.get("add"):
            raise Invalid("未检索到可核验的攻略站点，请指定片区或希望去的地点。")
        matches=matches or [(0,None,[])]
        trace.append({"tool":"guide","day":key,"query":search,"hits":[r["id"] for r in retrieved]})
        delegated=[r for r in replacements if r["new"]=="从攻略选取"]
        alternatives={}
        if delegated:
            for row in delegated:
                pool=[]
                for name,poi in PLACES.items():
                    if name in prior or name in c["exclude"] or not poi["minutes"]:
                        continue
                    doc=self.kb.by_id.get(poi["evidence"])
                    if doc and name in doc["text"]:
                        offset=doc["text"].index(name)
                        pool.append({"place":name,"source":doc["id"],"excerpt":doc["text"][offset:offset+210]})
                from semantics import obj,arr,enum,STRING
                selected=self.model.ask("列出有直接文字支持游客所要求活动或时段的候选地点，每个摘录一句直接证据。"
                    "仅有餐饮或景点的一般介绍，不足以保证某个特定时段或活动。多栏手册仅选属于该地点的原句。"
                    "能够直接支持主题的全部列出，距离由程序计算。",{"游客":query,"待替换":row["old"],"资料":pool},380,
                    obj({"matches":arr(obj({"place":enum(p["place"] for p in pool),"quote":STRING}))})) if pool else {"matches":[]}
                quotes={item["place"]:item["quote"].strip() for item in selected["matches"]}
                verified=[]
                for p in pool:
                    quote=quotes.get(p["place"])
                    if not quote or quote not in p["excerpt"]:continue
                    strength=self.model.ask("只看这一条引文。它明确支持游客提出的具体活动/时段，还是仅仅属于同一大类？"
                        "不能用常识补上引文没有说明的限定。",{"游客要求":query,"地点":p["place"],"引文":quote},
                        85,obj({"支持程度":enum(["明确支持具体要求","仅一般相关或证据不足"])}))
                    if strength["支持程度"]=="明确支持具体要求":
                        verified.append({**p,"quote":quote})
                alternatives[row["old"]]=verified
            from itertools import product
            choices=[]
            for group in product(*(alternatives[r["old"]] if r in delegated else [{"place":r["new"]}] for r in replacements)):
                swaps=[(r["old"],p["place"]) for r,p in zip(replacements,group)]
                try:
                    seq,assessment=solve(c,prior,[],op.get("add",[])+[n for _,n in swaps],
                        op.get("remove",[])+[o for o,_ in swaps],old["audit"]["stops"],swaps)
                except Invalid:
                    continue
                travel=sum(stop["leg"] for stop in assessment["stops"])+assessment["last_leg"]
                rank=(len(set(seq)^set(prior)),sum(abs(seq.index(n)-prior.index(o)) for o,n in swaps),travel,assessment["arrival"])
                choices.append((rank,swaps))
            if not choices:
                raise Invalid("没有找到既符合本轮兴趣又能通过行程审核的替换地点。")
            _,best=min(choices)
            replacements=[{"old":o,"new":n} for o,n in best]
            trace.append({"step":"compare_replacements","alternatives":alternatives,"ranked":sorted(choices),"selected":best})
        failures=[]
        attempted=set()
        while matches:
            _,guide_id,order=matches.pop(0)
            order=[n for n in order if n not in op.get("avoid",())]
            if (guide_id,tuple(order)) in attempted:
                continue
            attempted.add((guide_id,tuple(order)))
            try:
                swaps=[]
                for row in replacements:
                    n=row["new"]
                    if n=="从攻略选取":
                        n=next((p for p in order if p not in prior and p not in c["exclude"]),None)
                    if not n:
                        raise Invalid("该攻略没有合适的新站点")
                    swaps.append((row["old"],n))
                route,check=solve(c,prior,order,op.get("add",[])+[n for _,n in swaps],
                                  op.get("remove",[])+[p for p,_ in swaps],
                                  old["audit"]["stops"] if old else [],swaps,preserve_guide_order=bool(template and guide_id==template["id"]))
            except Invalid as err:
                failures.append(str(err))
                trace.append({"day":key,"attempt":guide_id,"audit_error":str(err)})
                if len(failures)==1 and not op.get("strict_template"):
                    retry=self.model.ask("""重新规划检索策略。上一候选未通过程序审核。不能修改约束。
可换攻略检索词，或判断所有硬约束无法兼容。输出 {query:新的简短检索词}，无可行方案时返回空字符串。""",
                        {"query":query,"contract":c,"prior":prior,"rejected":order,"error":str(err)},160)
                    if isinstance(retry.get("query"),str) and retry["query"].strip():
                        retry_rows=self.tool("guide",retry["query"],8)
                        matches.extend(guide_candidates(retry_rows,c["must"]))
                        trace.append({"tool":"guide","replan":retry["query"],"hits":[r["id"] for r in retry_rows]})
                continue
            verify=evaluate(c,route)
            if verify["violations"] or verify!=check:
                raise Invalid("行程未通过同一约束的最终复核")
            trace.append({"step":"admitted","day":key,"guide":guide_id,"order":route,
                          "audit":verify,"constraints":deepcopy(c)})
            before={s["place"]:s for s in old["audit"]["stops"]} if old else {}
            diff={"added":[n for n in route if n not in prior],"removed":[n for n in prior if n not in route],
                  "retimed":[s["place"] for s in verify["stops"] if s["place"] in before and s!=before[s["place"]]]}
            origin_guide=old["guide"] if old else guide_id
            evidence=self.kb.by_id.get(origin_guide)
            card=dict(contract=c,order=route,audit=verify,diff=diff,
                        guide=origin_guide,guide_source=({k:evidence[k] for k in ("title","source","locator","edition")}
                                                        if evidence else None),
                        guide_consulted=guide_id,estimate="转场为保守预算，非实时导航；起点未指定时从首站算起。")
            calendar_label=op.get("calendar_label") or (old or {}).get("calendar_label")
            if old and old.get("template"):
                card["template"]=deepcopy(old["template"])
                card["guide_source"]=deepcopy(old["guide_source"])
            elif template and guide_id==template["id"]:
                src=template["source"]
                ref=self.kb.by_id.get(src,{})
                pages={"metro-three":["202","202","203"],"hankou-day":["201"],"hanyang-day":["200"]}
                locator=pages.get(template["id"],[])[int(key)-1] if template["id"] in pages else ref.get("locator","线路原文")
                card["guide_source"]={"title":template["title"],"locator":locator,"source":ref.get("source",CITY_SOURCE),
                                      "edition":ref.get("edition","武汉市文化和旅游局 2020-08-12")}
                card["template"]={"id":template["id"],"day":int(key),"total_days":len(template["days"]),
                                  "source_order":source_order}
            if card.get("template"):
                source_order=card["template"]["source_order"]
                card["template"]["skipped"]=[name for name in source_order if name not in route]
                card["template"]["added"]=[name for name in route if name not in source_order]
                if not set(source_order)&set(route):
                    card["template"]["adaptation"]="根据必去点重排，当天未采用原版站点"
            if calendar_label:card["calendar_label"]=calendar_label
            if alternatives:
                card["replacement_evidence"]=[{"place":p["place"],"source_id":p["source"],"quote":p["quote"]}
                    for old_name,new_name in swaps for p in alternatives.get(old_name,[]) if p["place"]==new_name]
            return card
        detail=failures[0] if failures else "缺少可行路线"
        raise Invalid(detail+"。可以调整可用时段，或指定哪个站点可以舍弃。")

    def respond(self,sid,q,req=None):
        token=transport_cache.set({})
        try:
            return self._respond(sid,q,req)
        finally:
            transport_cache.reset(token)

    def _respond(self,sid,q,req=None):
        if not q.strip() or not sid.strip():
            raise ValueError("请提供会话和问题")
        req=req or uuid4().hex
        rev,state,cached=self.store.read(sid,req,q)
        if cached:
            return cached
        draft,result=self.execute_turn(q,state)
        result["revision"]=rev+1
        return self.store.save(sid,req,q,rev,draft,result)

    def execute_turn(self,q,state,*,component=False,compiled=None):
        trace=[]
        draft=deepcopy(state)
        citations=[]
        parts=[]
        mode="clarify"
        preview=None
        independent=[]
        deliveries=None
        try:
            spec=compiled if compiled is not None else self.understand(q,state)
            if spec["mode"]=="compose":
                if component:
                    raise Invalid("这个子任务仍包含多个独立请求，需要拆开。")
                from deliverables import orchestrate
                draft,deliveries,parts,citations=orchestrate(self,q,state,trace)
                spec={"mode":"compose"}
            mode=spec["mode"]
            trace.append({"step":"semantic_contract","mode":mode,"affected_days":spec.get("days",[]),
                          "rejected_constraints":spec.get("rejected_constraints",[])})
            jobs=[j for j in spec.get("tools",[]) if j["name"]!="guide" or mode not in ("plan","edit","preview")]
            if spec.get("batch"):
                from visitor_knowledge import answer_questions
                independent,citations=answer_questions(self.model,self.kb,[j for j in jobs if j["name"]!="location"],trace,original=q)
                map_answers,map_sources=self.consult([j for j in jobs if j["name"]=="location"],trace)
                independent.extend(map_answers)
                citations.extend(map_sources)
                records=spec.get("records",[])
                if records:
                    independent.extend(v for _,v in records)
                    trace.append({"step":"session_read","query":q,"records":[k for k,_ in records]})
            elif mode!="compose":
                independent,citations=self.consult(jobs,trace)
            for prompt in spec.get("reads",[]):
                from session_answers import recall
                answer,refs=recall(self.model,prompt,state)
                independent.append(answer)
                trace.append({"step":"session_read","query":prompt,"records":refs})
            if mode=="inspect_preview":
                mode="info"
                for label,version in (("正式行程",state["days"]),("未确认备选",state["pending_days"])):
                    for day,card in version.items():
                        stops=" → ".join(hhmm(stop["start"])+" "+stop["place"] for stop in card["audit"]["stops"])
                        parts.append(f"{label}第{day}天 {hhmm(card['contract']['start'])} 出发，{stops}。")
                trace.append({"step":"version_read","versions":["days","pending_days"]})
            if mode in ("confirm_preview","undo","restore_first"):
                history=state.get("past_days",[])
                if mode=="confirm_preview":
                    target=state.get("pending_days")
                elif mode=="undo":
                    target=history[-1] if history else None
                else:
                    target=state.get("first_days")
                if not target:
                    raise Invalid("目前没有可采用或恢复的那个版本。你指的是哪一天的哪项安排？")
                if mode=="undo":
                    draft["past_days"]=deepcopy(history[:-1])
                elif target!=state["days"]:
                    draft["past_days"]=(history+[deepcopy(state["days"])])[-8:]
                draft["first_days"]=state.get("first_days") or deepcopy(state["days"] or target)
                draft["days"]=deepcopy(target)
                draft.pop("pending_days",None)
                trace.append({"step":"version_selected","action":mode})
                parts.append("已采用刚才的预览。" if mode=="confirm_preview" else "已恢复你选的行程。")
                for day,card in target.items():
                    parts.append("第"+day+"天："+" → ".join(hhmm(s["start"])+" "+s["place"] for s in card["audit"]["stops"]))
                mode="edit"
            if spec["mode"]=="edit" and not state["days"]:
                raise Invalid("当前会话还没有已确认的行程，需要先建一张行程卡。")
            if mode=="clarify":
                raise Invalid(spec.get("question") or "你希望调整哪天的哪一站？")
            if mode=="info" and spec.get("question"):
                parts.append(spec["question"])
            if spec.get("unsupported"):
                raise Invalid("这些条件目前无法核实："+ "、".join(spec["unsupported"])+"。是否接受先核实这些信息后再安排行程？")
            apply_facts(draft,spec.get("facts",[]),q)
            if spec["mode"] in ("plan","edit","preview"):
                ops=spec.get("days",[])
                if mode in ("preview","edit"):rebind_overnights(ops,state["days"])
                if not ops or len(ops)>7:
                    raise Invalid("需要明确要安排或调整的日期")
                seen=set()
                occupied={k:v["order"] for k,v in state["days"].items()}
                for op in ops:
                    number=op["day"]
                    if type(number) is not int or not 1<=number<=7 or number in seen:
                        raise Invalid("日期编号无效或重复")
                    seen.add(number)
                    key=str(number)
                    if "mobility" in op:
                        guide=next((g for g in GUIDES if g["id"]==op.get("template")),None)
                        if guide and guide.get("preferred_mode"):op["mobility"]["default_preference"]=guide["preferred_mode"]
                        values=settings(op["mobility"])
                        hotel=values.get("住宿锚点")
                        if hotel and mode=="plan":
                            if number>1:op["set"].setdefault("origin",hotel)
                            if number<max(o["day"] for o in ops):op["set"].setdefault("destination",hotel)
                        other={n for k,stops in occupied.items() if k!=key for n in stops}
                        other.update(n for later in ops if later["day"]!=number for n in later.get("require",[]))
                        op["avoid"]=sorted(other-set(op.get("require",[]))-set(op.get("add",[])))
                    card=self.day(key,op,state["days"].get(key),trace)
                    occupied[key]=card["order"]
                    draft["days"][key]=card
                    seq=" → ".join(f"{hhmm(s['start'])}–{hhmm(s['end'])} {s['place']}" for s in card["audit"]["stops"])
                    msg=f"第{key}天：{seq}。"
                    c=card["contract"]
                    if "mobility" in c:
                        vals=settings(c["mobility"])
                        if vals.get("人数"):msg+=f" 当日{vals['人数']}人。"
                        if c["mobility"].get("duration_assumption"):msg+=" "+c["mobility"]["duration_assumption"]+"。"
                        for rule in c["mobility"]["rules"]:
                            if rule["field"]=="单段步行上限米":msg+=f" {rule['subject'] or '同行者'}每段转场步行上限{rule['value']}米。"
                        if card.get("guide_source"):
                            msg+=" 参考《"+card["guide_source"]["title"]+"》"
                            if card.get("template"):msg+=f"原攻略第{card['template']['day']}天"
                            msg+="。"
                            if card.get("template",{}).get("skipped"):
                                msg+=" 原版中本日未排："+ "、".join(card["template"]["skipped"])+"。"
                            if card.get("template",{}).get("added"):
                                msg+=" 按要求增加："+ "、".join(card["template"]["added"])+"。"
                        for leg in card["audit"]["legs"]:
                            if leg["origin"]==leg["destination"]:continue
                            detail=leg.get("directions","路线待核实")
                            if leg.get("cars"):detail+=f"，需{leg['cars']}辆普通出租车"
                            if leg.get("group_fare") is not None:detail+=f"，全团约{leg['group_fare']:g}元"
                            if leg.get("walk_m") is not None:detail+=f"，转场步行约{leg['walk_m']}米"
                            msg+=f"\n{leg['origin']} → {leg['destination']}：{LABEL[leg['mode']]}约{leg['minutes']}分钟，{detail}。"
                        available_until=min(c["end"],c["start"]+c["max_minutes"])
                        if card["audit"]["arrival"]+c["buffer"]<available_until-120 and not c["destination"]:
                            msg+=f" 已排站点结束后至{hhmm(available_until)}有自由时间，可作休息或追加游览。"
                    if c["destination"]:
                        msg+=f" 预计 {hhmm(card['audit']['arrival'])} 到{c['destination']}，另留 {c['buffer']} 分钟。"
                        if c["buffer"]:
                            msg+=f" 按 {hhmm(c['end'])} 的约定，最晚应在 {hhmm(c['end']-c['buffer'])} 到达。"
                    if card["diff"]["removed"]:
                        msg+=" 为满足新的行程条件，删去"+"、".join(card["diff"]["removed"])+"。"
                    for item in card.get("replacement_evidence",[]):
                        msg+=" 选择"+item["place"]+"的依据是“"+item["quote"]+"”。"
                    parts.append(msg)
                trip_audit=trip_review(draft["days"])
                trace.append({"step":"trip_review","audit":trip_audit})
                for link in trip_audit["overnights"]:
                    if link["status"]=="同一锚点":parts.append(f"第{link['from_day']}天结束和第{link['to_day']}天集合均在{link['next_start']}。")
                parts.append("转场时间为规划估算；步行距离按地图集合点之间的路网计算。园内步行、当日班次和入场条件请在出发前核实。")
                if mode=="preview":
                    parts.insert(0,"这是备选方案，正式行程仍按原卡执行。" if state["days"] else "这是尚未采纳的备选方案。")
                    preview=deepcopy(draft["days"])
                    draft=deepcopy(state)
                    draft["pending_days"]=preview
                elif draft["days"]!=state["days"]:
                    if state["days"]:
                        draft["past_days"]=(state.get("past_days",[])+[deepcopy(state["days"])])[-8:]
                    draft.setdefault("first_days",deepcopy(state["days"] or draft["days"]))
                    draft.pop("pending_days",None)
            if spec.get("facts") and mode!="preview":
                parts.append("已更新你的记录："+"；".join(dict.fromkeys(f["quote"].rstrip("。！？") for f in spec["facts"]))+"。")
            if not parts and not independent:
                # Nothing to look up or schedule: greet, thank, explain what we do, or admit what we lack.
                refs=[]
                if state["days"] or state["facts"]:
                    from session_answers import recall
                    answer,refs=recall(self.model,q,state)
                    if refs:
                        parts.append(answer)
                        trace.append({"step":"session_read","query":q,"records":refs})
                if not refs:
                    from small_talk import small_talk
                    parts.append(small_talk(self.model,q,state))
                    trace.append({"step":"small_talk"})
        except ValueError as err:
            draft=deepcopy(state)
            mode="clarify"
            parts=[str(err)]
            preview=None
        if mode=="compose":
            answer="\n\n".join(parts+independent)
        else:
            answer="\n".join(dict.fromkeys(line for part in parts+independent for line in part.splitlines()))
        offers=[n for row in trace if row.get("step")=="offered_places" for n in row["names"]]
        draft["turns"]=(state["turns"]+[{"user":q,"answer":answer,"offered_places":offers,"sources":list(dict.fromkeys(c["id"] for c in citations))}])[-12:]
        result=dict(answer=answer,mode=mode,days=draft["days"],preview=preview,citations=citations,
                    facts=draft["facts"],trace=trace)
        if deliveries is not None:result["deliverables"]=deliveries
        return draft,result


def directions(place):
    """How to get there: nearest metro station from the handbook access table, then the map search link."""
    from transport import ACCESS, snapshot
    area=place["area"].split("；")[0]
    station=ACCESS.get(place["name"])
    text=f"{place['name']}在{area}。"
    if station:
        lines=[n for n,stops in snapshot("metro_lines.json")["lines"].items() if station in stops]
        text+=f"坐地铁到{station}站"+(f"（{'、'.join(lines)}）" if lines else "")+"，出站后按地图导航步行过去。"
    return text+f"地图导航：{place['map_url']}"
