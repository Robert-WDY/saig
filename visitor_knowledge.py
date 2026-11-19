"""Answer a turn's public questions together; citations are bound to the retrieved rows of each question."""
import re
from knowledge import TOOLS
from semantics import arr,enum,obj,STRING

def english(text):
    """Visitors writing mostly Latin letters get English answers; citations stay verbatim Chinese."""
    letters=re.findall(r"[A-Za-z]",text or "");han=re.findall(r"[\u4e00-\u9fff]",text or "")
    return len(letters)>=12 and len(letters)>3*len(han)

def answer_questions(model,kb,jobs,trace,original=None):
    en=english(original or " ".join(j.get("query","") for j in jobs))
    searches={}
    candidates={}
    requested={}
    for job in jobs:
        name,q=job["name"],job["query"].strip()
        if not q or (name,q) in searches:continue
        rows=kb.search(q,TOOLS[name],8)
        names=job.get("candidates",[])
        requested[name,q]=job.get("所求答案类型","")
        candidates[name,q]=names
        if names:
            rows[:0]=[kb.by_id[i] for i in job.get("context_sources",[]) if i in kb.by_id]
            rows.extend(d for n in names for d in kb.search(n,k=4) if n in d["text"])
        curated=[d for d in kb.curated if d["category"] in TOOLS[name]]
        searches[name,q]={d["id"]:d for d in [*rows,*curated]}
        trace.append({"tool":name,"query":q,"hits":list(searches[name,q])})
    if not searches:return [],[]
    tasks={str(i):q for i,(_,q) in enumerate(searches,1)}
    pools=dict(zip(tasks,searches.values()))
    docs={d["id"]:d for rows in pools.values() for d in rows.values()}
    excerpts={}
    reviewed={d["id"] for d in kb.curated}
    for doc in docs.values():
        sentences=[doc["text"]] if doc["id"] in reviewed else re.findall(r"[^。！？\n]+[。！？]?",doc["text"][:1200])
        for j,sentence in enumerate(sentences):
            excerpt=sentence.strip()
            if excerpt:excerpts[f"{doc['id']}#{j}"]=(doc,excerpt)
    permitted={}
    for k,key in zip(tasks,searches):
        names=candidates[key]
        permitted[k]=[i for i,(doc,line) in excerpts.items() if doc["id"] in pools[k]
                      and (not names or any(n in line for n in names))]
    proposals={}
    if any(permitted.values()):
        allowed=set().union(*permitted.values())
        row=obj({"问题编号":enum(tasks),"引文编号":STRING,"给游客的回答":STRING})
        result=model.ask("为每个游客问题分别作答，以该问题允许引用的资料为依据。结合原话理解各子问题。仅在询问去哪里时推荐地点；食物、项目、所需材料等请列对应名称。"
            "先辨认问题索取的是哪个字段和哪一类实例，在答复中明确给出该类型的具体值。只介绍与之有关的位置或背景无法交付所求实例。每项问题至少检查一次，选择最直接的引文。访问者询问能学什么时，区分资料记载的培养方式和无需预约即可参加的活动；"
            "可以准确介绍前者而不承诺后者。选择规划中的设施时必须表明尚处规划。每条答案只说一条可以由引文证明的事实或建议，并选一个允许的引文编号。"
            "介绍、概览、是什么、值得了解、怎么参加这类开放问题，同一问题要给3到5条答案，每条讲一个不同方面并引用不同引文（城市：地理格局、历史文化、美食、代表景点；社区：定位、资源、学习方式、地点；赛事：参赛资格、必交材料、选填材料、时间节点、入口），语气像热情的城市接待员，可以写成完整的两句话。只问单一具体事实时给一到两条。限定候选时选一个候选地点作答，并在回答中写出地名。能确定的先答，"
            "尚缺的时间、地址细节等不要猜。资料只给出街区或项目名称也可回答位置。只提问某个场地时应清楚选出它。"
            "引文须支持同一主体、属性、范围。不要用泛泛介绍代替答复。采用同一事项最新的已核对公告，分别处理不同期限。无对应证据的问题不生成条目。一篇文章没有提及某事不能作为该事无规定的依据。"
            +("游客用英文提问：给游客的回答必须用自然流畅的英文忠实转述引文，地名写拼音或通用英文名并在括号保留中文，例如 Yellow Crane Tower (黄鹤楼)。固定译名：SPU 全称 Super Person Unit（超级个体单元），数命 = Shuming，智民里 = Zhiminli，SAIG 不译。" if en else ""),
            {"游客原话":original,"问题":tasks,"每个问题应交付的取值类型":dict(zip(tasks,requested.values())),"若有限定必须从中选择":dict(zip(tasks,candidates.values())),
             "各题允许的引文":permitted,"引文":{i:{"标题":excerpts[i][0]["title"],"版本":excerpts[i][0]["edition"],"内容":excerpts[i][1]} for i in excerpts if i in allowed}},1600,obj({"答复":arr(row)}))
        for item in result["答复"]:
            k=item["问题编号"]; source=item["引文编号"]
            if source not in permitted[k]:continue
            doc,quote=excerpts[source];claim=item["给游客的回答"].strip()
            choices=candidates[list(searches)[int(k)-1]]
            if doc and quote and claim and quote in doc["text"] and (not choices or any(n in claim and n in quote for n in choices)):
                proposals[str(len(proposals)+1)]=(k,doc,quote,claim)
    approved=[]
    if proposals:
        packet={i:{"游客原话":original,"当前子问题":tasks[k],"所求取值类型":list(requested.values())[int(k)-1],"原文":quote,"回答":claim} for i,(k,doc,quote,claim) in proposals.items()}
        decision=model.ask(("回答是英文译述，按语义与中文原文比对，忠实翻译视同支持。" if en else "")+"一次审核所有候选答案。只有直接回答所问、地点范围与引文相符，且引文支持每项事实时才批准。"
            "引用另一个地点的开放时间即使加上免责声明也不得批准。规划中的体验不能描述成已可进场，"
            "需要区分项目实战带教学员与公众参观设施。"
            "推荐某地点允许基于引文中明确的地点特征做有说明的主观建议；不能由日间信息推断夜间开放或费用。"
            "核对答案提供的值属于所问对象类型；只给关联对象或地点却没有所求实例，应拒绝。数字合计不可拆分。区分未经证实的要求和已证实的边界。为获准的旅游推荐逐字列出真正建议游客前往的各个具体地点；"
            "出发位置、用来限定范围的城区或街道不属于候选。其他问答这一项为空。",packet,260,
            obj({"批准":arr(enum(proposals)),"建议去的地点":arr(obj({"编号":enum(proposals),"地点":STRING}))}))
        approved=list(dict.fromkeys(decision["批准"]))
        offers=[]
        for row in decision["建议去的地点"]:
            idx,n=row["编号"],row["地点"].strip()
            if idx in approved and n and n in proposals[idx][2] and n in proposals[idx][3] and n not in offers:
                offers.append(n)
        if offers:trace.append({"step":"offered_places","names":offers})
    parts=[];citations=[]
    for k,(name,q) in zip(tasks,searches):
        selected=[]
        for i in approved:
            idx,doc,quote,claim=proposals[i]
            if idx!=k:continue
            parts.append(claim)
            citations.append({**{f:doc[f] for f in ("id","source","title","locator","edition")},"quote":quote,"claim":claim})
            selected.append(doc["id"])
            if doc["id"]=="register":parts.append(("Official registration: " if en else "官方报名入口：")+doc["source"])
        if not selected:parts.append(f"The official materials don't confirm \"{q.strip('？?')}\" yet; please check with the organisers." if en
                                     else f"现有资料不足以确认「{q.strip('？?')}」，需要向相关方核实。")
        trace.append({"step":"answered_question","tool_name":name,"query":q,"supported":bool(selected),"sources":selected})
    return parts,citations
