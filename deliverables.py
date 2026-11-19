"""Plan and execute independently verifiable visitor deliverables in one session transaction."""
from copy import deepcopy
from graphlib import TopologicalSorter, CycleError
from itertools import combinations
import re
from uuid import uuid4

import requests
from planning import Invalid, evaluate
from knowledge import TOOLS
from semantics import arr, enum, obj, STRING
from trip_contract import GUIDES, trip_review
from option_conditions import compile_options, compile_contract

KINDS=("plan","revise","show","adopt","compare","info","remember","clarify")
AXES=("景点","节奏","交通","转场步行","交通费用")
TASK=obj({"id":STRING,"kind":enum(KINDS),"title":STRING,"request":STRING,
          "source":STRING,"constraints":arr(STRING),"inputs":arr(STRING),
          "days":{"type":"integer","minimum":0,"maximum":7},"axes":arr(enum(AXES)),
          "topic":enum(["无",*TOOLS,"location"]),"target_days":arr({"type":"integer","minimum":1,"maximum":7}),
          "preview":{"type":"boolean"},"compare_prior":{"type":"boolean"}})

def order_tasks(tasks,catalog,question):
    if not tasks:raise Invalid("未取得可执行的交付清单。")
    ids=[t["id"] for t in tasks]
    if len(ids)!=len(set(ids)) or set(ids)&set(catalog) or any(not i.strip() for i in ids):
        raise Invalid("交付物编号冲突。")
    known=set(ids)|set(catalog)
    graph={}
    kinds={**dict.fromkeys(catalog,"plan"),**{t["id"]:t["kind"] for t in tasks}}
    revisions={}
    for task in tasks:
        if task["kind"]=="revise" and len(task["inputs"])==1:
            parent=task["inputs"][0]
            if parent in revisions:raise Invalid("同一方案的改动请合并到一个任务。")
            revisions[parent]=task["id"]
    for t in tasks:
        refs=t["inputs"]; kind=t["kind"]
        if kind=="compare" and not t["compare_prior"]:
            refs=list(dict.fromkeys(revisions.get(ref,ref) for ref in refs))
            t["inputs"]=refs
        if not t["source"].strip() or t["source"] not in question or any(not c.strip() or c not in question for c in t["constraints"]):
            raise Invalid("交付物或条件缺少游客原文依据。")
        if not t["request"].strip() or not t["title"].strip():raise Invalid("交付说明为空。")
        if len(refs)!=len(set(refs)) or not set(refs)<=known:raise Invalid("依赖引用不唯一或不存在。")
        if kind in ("revise","show","adopt") and len(refs)!=1:raise Invalid("此操作需要唯一的原方案。")
        if kind=="revise":
            if not t["target_days"] or len(set(t["target_days"]))!=len(t["target_days"]):raise Invalid("修改需要明确的行程日期范围。")
            if refs[0] in catalog and any(str(day) not in catalog[refs[0]]["days"] for day in t["target_days"]):
                raise Invalid("修改日期不在原方案内。")
        if kind=="compare" and len(refs)<2:raise Invalid("比较需要至少两份不同的行程。")
        if kind=="plan" and (not t["days"] or refs):raise Invalid("新方案需要独立的天数和空起始状态。")
        if kind=="info" and t["topic"]=="无":raise Invalid("资料任务缺少检索领域。")
        if kind in ("revise","show","adopt","compare") and any(kinds[r] not in ("plan","revise","show","adopt","clarify") for r in refs):
            raise Invalid("引用对象不是行程。")
        graph[t["id"]]=[r for r in refs if r not in catalog]
    try:return tuple(TopologicalSorter(graph).static_order())
    except CycleError as exc:raise Invalid("交付物之间存在循环依赖。") from exc

def make_tasks(model,q,catalog,history):
    phrases={str(i):part.strip() for i,part in enumerate(re.findall(r"[^，,；;。！？!?\n]+",q),1) if part.strip()}
    if not phrases:raise Invalid("请说明希望收到哪些行程或资料。")
    task_schema=obj({**TASK["properties"],"source":enum(phrases),"constraints":arr(enum(phrases))})
    schema=obj({"tasks":arr(task_schema),"clarification":STRING})
    options={k:{"名称":v["title"],"各天的景点":{n:c["order"] for n,c in v["days"].items()},
                "版本":v.get("version",1)} for k,v in catalog.items()}
    context={"游客原话":q,"原文编号":phrases,"已有方案":options,"上轮问题":[h["user"] for h in history[-2:]]}
    instruction="""列出游客要拿到的每一项独立交付物，生成依赖图。plan 是一整套可独立使用的行程，一套多日游只建一个任务；
不同方案即使天数相同也分别建。revise 修改指名的某个方案；show 读取；adopt 只在游客明确选定正式使用时创建。
历史问答仅用于理解本轮的指代和明确要求沿用的条件。先前的知识咨询或提到的事物不自动成为本轮新行程的必去点或体验约束。
revise 的 target_days 只填实际修改的旅行日序。游客说保持原样的方案或日期不要创建修改任务。若明确只想看效果，preview 为 true，否则为 false。其他类型的 target_days 为空。
compare 依赖所有被比较的真实方案；info 是独立的、有资料可核查的问题，包括公共介绍或餐饮建议。
同轮需要改完再比较时，inputs 引用修改任务和其余方案，而非修改前的版本。只有游客明确要比同一方案的修改前后时 compare_prior 才为 true。
info 的 topic 填对应知识工具：社区位置、场地运营和带教选 community，纯地图坐标才选 location；其余任务填无。
remember 仅用于明确授权保存或纠正个人资料，source 选择实际授权原句，并在 constraints 引用该项完整原文。
为每项写 t1、t2 等唯一 id、可独立理解的中文标题、完整独立 request。新行程标题用区域或主题及总天数区分，勿附可能后续变化的景点和钟点。source 只填一个体现该交付的原文编号，
constraints 列全天数以外需单独验收的全部要求所对应的原文编号，即使与 source 是同一句也要列；共同要求复制给每个适用方案，局部条件只给所属方案。request 必须包含该交付适用的所有条件。不要把其他交付物写入 request。
inputs 只填任务 id 或已有方案的实际键。新方案的 days 填明确的旅行天数（支持一至七天）。对比维度从 axes 选；
未指定时选景点、节奏、交通。仅提到方案时不能擅自采用。只拆意图，不在此处判断事实真伪和路线可行性；即使时间不够也交给排程程序核验。
用户原文里的场所名称直接交给资料检索，不要求用户先核实名词。若某一交付的指代确实不唯一或超出支持范围，将其单独列为 clarify 节点，request 写明确缺什么，其他节点照常执行。仅当整句话无法拆出任何交付时填顶层 clarification。"""
    for attempt in range(2):
        response=model.ask(instruction,context,1900,schema)
        tasks=response["tasks"]
        if not tasks and response["clarification"].strip():raise Invalid(response["clarification"])
        for t in tasks:
            t["source"]=phrases[t["source"]]
            t["constraints"]=[phrases[c] for c in dict.fromkeys(t["constraints"])]
        try:
            order=order_tasks(tasks,catalog,q)
            check=model.ask("逐项核对清单是否覆盖游客明确要求的每份成果、天数、共同/局部约束和依赖方向。"
                "确保没有把两套方案合并、丢掉比较、擅自采纳、误改保持原样的日期或把约束串给其他方案。无需判断路线本身的可行性。"
                "非天数的具体要求也必须出现在各自的 constraints。历史知识咨询不能擅自升级成本轮硬约束。判定清单是否正确，并给出简短依据。",
                {"原话":q,"清单":tasks,"可引用方案":context["已有方案"]},180,obj({"完整且正确":{"type":"boolean"},"依据":STRING}))
            if not check["完整且正确"]:raise Invalid(check["依据"] or "清单未覆盖全部要求。")
            return tasks,order
        except Invalid as exc:
            if attempt:raise
            context={**context,"需纠正的问题":str(exc),"原清单":tasks}

def check_days(days,count,original=None,affected=None,compiled=None):
    if not days or set(days)!={str(i) for i in range(1,count+1)}:
        raise Invalid(f"未交付完整的 {count} 天游览卡。")
    touched=set(days) if affected is None else {str(n) for n in affected}
    if original is not None and any(days[n]!=original[n] for n in days.keys()-touched):
        raise Invalid("检测到未授权日期发生变动。")
    expected={}
    if compiled:
        from agent import apply_constraints
        for op in compiled["days"]:
            key=str(op["day"])
            expected[key]=apply_constraints((original or {}).get(key,{}).get("contract",{}),op)
    for n in touched:
        card=days[n]
        if n in expected and card["contract"]!=expected[n]:
            raise Invalid(f"第{n}天的排程未使用该方案的独立约束。")
        if not card["order"]:raise Invalid("行程有空白的一天。")
        audit=evaluate(card["contract"],card["order"])
        if audit["violations"] or audit!=card["audit"]:raise Invalid("行程卡未通过既有约束的复算。")
    return trip_review(days)

def metrics(days):
    stats=trip_review(days)["days"]
    places=[n for card in days.values() for n in card["order"]]
    legs=[leg for card in days.values() for leg in card["audit"].get("legs",[]) if leg["origin"]!=leg["destination"]]
    def total(field):
        recorded=sum(leg["minutes"] for leg in legs)
        if recorded!=sum(d["transfer_minutes"] for d in stats.values()) or any(leg.get(field) is None for leg in legs):return None
        return sum(leg[field] for leg in legs)
    return {"days":len(days),"places":list(dict.fromkeys(places)),"stops":len(places),
            "daily_stops":[len(days[str(n)]["order"]) for n in range(1,len(days)+1)],
            "visit_min":sum(d["visit_minutes"] for d in stats.values()),
            "transfer_min":sum(d["transfer_minutes"] for d in stats.values()),
            "walk_m":total("walk_m"),"group_fare":total("group_fare"),
            "arrivals":[{"day":n,"destination":c["contract"]["destination"],"arrival":c["audit"]["arrival"],
                         "deadline":c["contract"]["end"]-c["contract"]["buffer"]}
                         for n,c in days.items() if c["contract"]["destination"]]}

def compare(options,axes):
    summaries=[metrics(o["days"]) for o in options]
    axes=set(axes or ("景点","节奏","交通"))
    lines=[]
    for opt,m in zip(options,summaries):
        text=[f"{m['days']}天，共{m['stops']}个游览站次"]
        if "节奏" in axes:
            text.append("每天分别安排"+"、".join(map(str,m["daily_stops"]))+f"站，预计游览{m['visit_min']}分钟")
        if "交通" in axes:
            from agent import hhmm
            text.append(f"全程预计转场{m['transfer_min']}分钟")
            for a in m["arrivals"]:
                text.append(f"第{a['day']}天预计{hhmm(a['arrival'])}到{a['destination']}，最晚{hhmm(a['deadline'])}到")
        if "转场步行" in axes:text.append(f"转场步行约{m['walk_m']}米" if m["walk_m"] is not None else "部分路段缺步行数据，无法合计")
        if "交通费用" in axes:text.append(f"全团交通约{m['group_fare']:g}元" if m["group_fare"] is not None else "缺少完整的全团交通费依据")
        lines.append(opt["title"]+"："+ "，".join(text)+"。")
    if "景点" in axes:
        for a,b in combinations(range(len(options)),2):
            x,y=summaries[a]["places"],summaries[b]["places"]
            lines.append(f"{options[a]['title']}与{options[b]['title']}共同游览："+("、".join(p for p in x if p in y) or "没有重复景点")+"。")
            for i,first,second in ((a,x,y),(b,y,x)):
                lines.append(f"仅{options[i]['title']}安排："+("、".join(p for p in first if p not in second) or "无")+"。")
    if "节奏" in axes and len(options)==2:
        a,b=summaries
        density=[m["stops"]/m["days"] for m in (a,b)]
        if density[0]!=density[1]:
            i=0 if density[0]<density[1] else 1
            lines.append(f"按每天的游览站数，{options[i]['title']}更宽松，平均每天{density[i]:g}站，另一套为{density[1-i]:g}站。")
    return "\n".join(lines),summaries

def choose(state,days):
    if state["days"]!=days:
        if state["days"]:state["past_days"]=(state.get("past_days",[])+[deepcopy(state["days"])])[-8:]
        state.setdefault("first_days",deepcopy(state["days"] or days))
        state["days"]=deepcopy(days)
    state.pop("pending_days",None)

def template_request(agent,task,state,*,conditions_compiled=False):
    if task["kind"]!="plan" or (task["constraints"] and not conditions_compiled) or state["facts"]:return None
    count=task["days"]
    matches={g["id"]:g for g in GUIDES if len(g["days"])==count and g["span"]=="day"}
    if not matches:return None
    hits=agent.tool("guide",task["request"],30)
    template=next((matches[r["id"].partition(".day")[0]] for r in hits
                   if r["id"].partition(".day")[0] in matches),None)
    if template is None:
        template=next(iter(matches.values()))
    return {"mode":"plan","days":[{"day":day,"query":task["request"],"template":template["id"],
            "mobility":{"rules":[]},"set":{}} for day in range(1,count+1)]}

def verify_content(model,t,answer,days):
    if t["kind"]=="plan" and not t["constraints"]:
        return
    snapshot={d:{"约束":card["contract"],"顺序":card["order"]} for d,card in days.items()}
    result=model.ask("核对已实际生成的单项交付是否满足任务中所有明确的要求和适用范围。"
        "凭已生成的日卡、回答判断，不允许假设存在未交付内容。仅在有确切漏项或违反条件时判不满足，在依据中指出具体差异。"
        "审核的唯一约束依据是游客原句和该方案绑定的条件；仅有知识咨询背景不能变成游览承诺。只核对当前这个独立任务。原文片段可能同时请求多套行程，只检查该片段对当前方案明确适用的条件。"
        "已完成的天数和时间算术由程序核验，无须重审。",{"交付类型":t["kind"],"方案天数":t["days"],"游客原句":t["source"],"适用条件":t["constraints"],
        "日卡":snapshot,"回答":answer},200,obj({"满足用户要求":{"type":"boolean"},"依据":STRING}))
    if not result["满足用户要求"]:raise Invalid(result["依据"] or "成果与游客要求不一致。")

def orchestrate(agent,q,state,trace):
    draft=deepcopy(state)
    catalog=dict(state.get("options",{}))
    if state["days"]:catalog["current"]={"title":"当前正式行程","days":state["days"]}
    tasks,order=make_tasks(agent.model,q,catalog,state["turns"])
    bundles=compile_options(agent.model,tasks,catalog)
    trace.append({"step":"deliverable_plan","tasks":tasks,"execution_order":order})
    rows={t["id"]:{**t,"status":"pending"} for t in tasks}
    artifacts=dict(catalog); parts=[];citations=[]
    for key in order:
        row=rows[key];kind=row["kind"];refs=row["inputs"]
        missing=[r for r in refs if r in rows and rows[r]["status"]!="passed"]
        if missing:
            row.update(status="blocked",answer="所依赖的交付物尚未通过校验："+"、".join(rows[r]["title"] for r in missing)+"。")
            continue
        try:
            parents=[artifacts[r] for r in refs]
            if kind=="clarify":
                raise Invalid(row["request"])
            if kind in ("plan","revise","info","remember"):
                isolated={"days":deepcopy(parents[0]["days"]) if kind=="revise" else {},
                          "facts":deepcopy(state["facts"]),"turns":[]}
                prompt=row["request"]
                if kind=="info" and parents:
                    prompt+="\n参考已交付内容："+"；".join(p["title"]+" "+p["answer"] if "answer" in p else
                            p["title"]+" "+" / ".join("、".join(c["order"]) for c in p["days"].values()) for p in parents)
                if kind=="info":
                    from visitor_knowledge import answer_questions
                    retrieval=[]
                    jobs=[{"name":row["topic"],"query":prompt}]
                    if row["topic"]=="location":lines,sources=agent.consult(jobs,retrieval)
                    else:lines,sources=answer_questions(agent.model,agent.kb,jobs,retrieval)
                    result={"mode":"info","answer":"\n".join(lines),"citations":sources,"trace":retrieval}
                else:
                    if kind=="remember":
                        isolated["facts"]=deepcopy(draft["facts"])
                        prompt="，".join(dict.fromkeys([row["source"],*row["constraints"]]))
                    scoped=compile_contract(row,isolated["days"],bundles.get(key))
                    compiled,bindings=scoped or (template_request(agent,row,isolated),[])
                    if scoped and not bindings and kind=="plan":
                        template=template_request(agent,row,isolated,conditions_compiled=True)
                        if template is not None:
                            compiled,scoped=template,None
                    if bindings:row["bound_constraints"]=bindings
                    child,result=agent.execute_turn(prompt,isolated,component=True,compiled=compiled)
                row["execution"]=[s for s in result["trace"] if s.get("step") in
                                  ("semantic_contract","frozen_day","admitted","answered_question","trip_review")
                                  or s.get("tool") or s.get("audit_error")]
                answer=result["answer"]
                if result["mode"]=="clarify":raise Invalid(answer)
                row["checks"]={}
                if kind=="remember":
                    if child["facts"]==isolated["facts"]:raise Invalid("未确认个人资料有独立的写入结果。")
                    if any(f.get("quote","") not in q for f in child["facts"] if f not in isolated["facts"]):
                        raise Invalid("写入的资料未绑定到游客原文。")
                    draft["facts"]=child["facts"]
                    artifacts[key]={"title":row["title"],"answer":answer}
                    row["checks"]={"facts_written":True}
                elif kind=="info":
                    if result["mode"]!="info":raise Invalid("资料任务没有得到独立的资料答复。")
                    evidence=result["citations"]
                    if not evidence and not any(x.get("step")=="answered_question" or x.get("tool")=="location" for x in result["trace"]):
                        raise Invalid("没有可核对的检索结果。")
                    for c in evidence:
                        doc=agent.kb.by_id.get(c["id"])
                        if not doc or c["quote"] not in doc["text"] or c["source"]!=doc["source"] or c["claim"] not in answer:
                            raise Invalid("引文与答复没有对齐。")
                    map_hits=any(s.get("tool")=="location" and (s["result"]["catalog"] or s["result"]["geocodes"]) for s in result["trace"])
                    row.update(citations=evidence,checks={"sources_checked":len(evidence),"supported":bool(evidence or map_hits)})
                    if not evidence and not map_hits:
                        row.update(status="unverified",answer=answer)
                        continue
                    citations.extend(evidence)
                    artifacts[key]={"title":row["title"],"answer":answer}
                else:
                    days=result["preview"] or result["days"]
                    original=isolated["days"] if kind=="revise" else None
                    count=len(original) if original is not None else row["days"]
                    if result["mode"] not in ("plan","edit","preview"):raise Invalid("未实际生成所请求的行程。")
                    if kind=="revise":
                        affected={str(n) for n in row["target_days"]}
                        actual={str(s["day"]) for step in result["trace"] if step.get("step")=="semantic_contract"
                                for s in step["affected_days"]}
                        if actual!=affected:raise Invalid("实际重排日期与授权范围不一致。")
                    check_days(days,count,original,row["target_days"] if original is not None else None,
                               scoped[0] if scoped else None)
                    verify_content(agent.model,row,answer,days)
                    option_id="option_"+uuid4().hex[:12]
                    title=row["title"]
                    version=1
                    if kind=="revise":
                        preview=row["preview"] or result["mode"]=="preview"
                        title=parents[0]["title"]
                        if preview:
                            title+="（试排）"
                        else:
                            option_id=parents[0].get("option_id",refs[0])
                            version=parents[0].get("version",1)+1
                        row["replanned_days"]=row["target_days"]
                    option={"title":title,"days":days,"option_id":option_id,"version":version}
                    if kind=="plan":option["answer"]=answer
                    if option_id=="current":
                        choose(draft,days)
                    else:
                        draft.setdefault("options",{})[option_id]=option
                    artifacts[key]=option
                    row.update(option_id=option_id,version=version,days_requested=count,cards=days,
                               checks={"day_count":count,"routes_recomputed":True,"scope":True})
            elif kind=="compare":
                answer,numbers=compare(parents,row["axes"])
                row["versions"]=[{"input":r,"option_id":p.get("option_id",r),"version":p.get("version",1)} for r,p in zip(refs,parents)]
                row.update(metrics=dict(zip(refs,numbers)),checks={"computed_from":refs})
                artifacts[key]={"title":row["title"],"answer":answer}
            else:
                option=parents[0]
                trip_review(option["days"])
                if kind=="adopt":choose(draft,option["days"])
                answer=("已采用该方案。\n" if kind=="adopt" else "")+(option.get("answer") or "\n".join(
                    f"第{n}天："+" → ".join(c["order"]) for n,c in option["days"].items()))
                artifacts[key]=option
                row.update(cards=option["days"],checks={"source":refs[0]})
            row.update(status="passed",answer=answer)
        except ValueError as exc:
            detail="外部服务暂时不可用。" if isinstance(exc,requests.RequestException) else str(exc)
            row.update(status="failed",answer="这项未能交付："+detail)
    for t in tasks:
        row=rows[t["id"]]
        parts.append(row["title"]+"\n"+row["answer"])
    trace.append({"step":"deliverable_results","statuses":{k:r["status"] for k,r in rows.items()}})
    return draft,list(rows.values()),parts,citations
