"""The language model resolves intent; the program binds and validates typed operations."""
import re
from places import PLACES

STRING={"type":"string"}
INT={"type":"integer"}
def arr(items):
    return {"type":"array","items":items}
def obj(properties,required=None):
    return {"type":"object","properties":properties,"additionalProperties":False,
            "required":list(properties) if required is None else required}
def enum(values):
    return {"type":"string","enum":list(values)}

MEM="""摘取本轮明确陈述的人物关系与偏好，只保存用户原话可以证明的内容；source填实际支持这条事实的原句编号。不要记录时钟和计划草案。
subject游客本人用self，游客妈妈用self.mother；其他同行者用一致的对象标识。姓名用name，喜好用likes（可多值），住处用stays_at。
已存在的主语、关系优先复用。替换用set，新增并存用add，撤销用remove。"""

def compile_day(raw,day,utterance):
    op={"day":day,"query":raw["query"],"set":{}}
    for x in raw["changes"]:
        if not x["quote"].strip() or x["quote"] not in utterance:
            raise ValueError("行程变更缺少本轮原文："+x["field"])
        k,v=x["field"],x["value"]
        if k=="max_minutes" and not re.search(r"分钟|小时|钟头|刻钟|半天",x["quote"]):
            raise ValueError("全日分钟预算须引用表示时长的原文")
        if k in ("require","unrequire","exclude","allow","add","remove"):
            op.setdefault(k,[]).append(v)
        elif k=="replace":
            op.setdefault("replacements",[]).append({"old":x["target"],"new":v})
        elif k in ("duration","window"):
            if x["target"] not in PLACES:
                raise ValueError("duration/window只允许绑定到目录内的具体地点。整天总时长属于max_minutes，已有起止时间就省略。")
            if k=="duration" and not re.search(r"分钟|小时|钟头|刻钟|半天",x["quote"]):
                raise ValueError("游览时长必须引用有时长单位的原话。日期或站数不能转换为停留分钟数。")
            table=op["set"].setdefault("durations" if k=="duration" else "windows",{})
            table[x["target"]]=int(v) if k=="duration" else v.split("-")
        elif k=="region":
            op["set"].setdefault("regions",[]).append(v)
        else:
            op["set"][k]=int(v) if k in ("max_stops","buffer","max_minutes") else v
    return op


MODES={"查询公开资料":"info","查询本会话":"recall","记录人物事实":"remember","新建行程":"plan",
       "更改原卡":"edit","只做试排":"preview","确认上次试排":"confirm_preview","撤销最近提交":"undo",
       "恢复初版":"restore_first","保留当前安排不动":"keep","须询问具体对象或偏好":"clarify",
       "硬性要求缺乏数据":"unsupported","两个要求本身相斥":"conflict"}
TOOLS_BY_PURPOSE={"城市概况历史地理":"wuhan","吃喝与早餐文化":"food","景区游览介绍":"attraction",
    "社区场地运营及学员培养":"community","SPU是什么及其能力责任":"spu","赛题功能要求评分选拔报名与提交":"saig",
    "查询地址经纬度导航":"location","游览线路攻略":"guide","本人的关系偏好或已确认的行程":"memory","仅背景情绪或回答格式要求":None}
TURN=obj({"本轮意图简述":STRING,"主要行动":enum(MODES),"涉及天":{**arr(INT),"maxItems":7}})
TOPIC=obj({"所问实体与属性":STRING,"资料类型":enum(TOOLS_BY_PURPOSE),"独立检索问题":STRING})
QUESTIONS=obj({"独立知识问题":{**arr(STRING),"maxItems":8}})
def interpret(model,q,memory,review,validate_op,split_tasks=True):
    from feedback import day_patch
    def extract_facts(text):
        spans={i:s for i,s in enumerate(re.findall(r"[^，。；！？!?;,]+",text),1)}
        result=[]
        if spans:
            schema=obj({"facts":arr(obj({"subject":STRING,"relation":STRING,"object":STRING,
                "source":{"type":"integer","enum":list(spans)},"op":enum(["set","add","remove"])}))})
            for f in model.ask(MEM,{"原句编号":spans,"已有事实":memory["facts"]},430,schema)["facts"]:
                f["quote"]=spans[f.pop("source")]
                if not f["object"].strip() or f["object"] not in f["quote"]:
                    exact=model.ask("将提取的事实值对齐到原句：逐字复制原句中作为对象的连续中文词组，不翻译、不改写。"
                        "没有对应原文就填空串。",{"原句":f["quote"],"关系":f["relation"],"初步理解":f["object"]},
                        90,obj({"逐字对象":STRING}))["逐字对象"].strip()
                    f["object"]=exact
                if f["object"] and f["object"] in f["quote"]:result.append(f)
        return result
    def split_memory_public():
        clauses=[s.strip() for s in re.split(r"[，。；！？!?;,：:]",q) if s.strip()]
        if len(clauses)>1:
            # Split only where private memory and a public question coexist. Other
            # compound route constraints retain their shared utterance and referents.
            numbered={str(i):part for i,part in enumerate(clauses,1)}
            ids=arr(enum(numbered))
            ownership=model.ask("逐项把独立请求绑定原文编号。明确纠正会话中已有的人物资料也是写入，应包括纠正语及新值。"
                "读回包括向你询问自己或亲友的资料，即使目的是填表；保留代词。公共问答包含实际公共提问和理解它所需的上下文。"
                "游客自己写东西、禁止保存和路线约束不构成存入。没有某类任务就给空数组。",
                {"原句编号":numbered,"已存关系":memory["facts"]},240,
                obj({"明确存入":ids,"读回":ids,"公共问答":ids}))
            def join(selected):
                return "，".join(text for key,text in numbered.items() if key in selected)
            save=join(ownership["明确存入"])
            read=join(ownership["读回"])
            public=join(ownership["公共问答"])
            if public and not save:
                authorization=model.ask("游客有没有在公共问题以外明确让接待员记住一项个人事实？"
                    "只在确有这项委托时，原样摘出委托用语，并选出陈述该个人事实的原句编号。"
                    "注意句号和逗号可以把委托与事实分开。游客自己填表、做笔记或要求不要记录，均返回空。",
                    {"完整原话":q,"原句编号":numbered},140,obj({"委托原词":STRING,"个人事实原句":ids}))
                phrase=authorization["委托原词"].strip()
                if phrase and phrase in q and authorization["个人事实原句"]:
                    save=phrase+"，"+join(authorization["个人事实原句"])
            if public and (save or read):
                result=interpret(model,public,memory,review,validate_op,False)
                if read:result.setdefault("reads",[]).append(read)
                if save:
                    intent=model.ask("整句话是否明确要求保存个人事实，或明确纠正已存的资料？纠正时可以用含正确值或指出错误的原话作依据。"
                        "只是做笔记、引用他人观点、核对文本或禁止写入都不构成授权。若授权给出逐字原话，否则填空。",
                        {"整句":q,"私人片段":save,"已存关系":memory["facts"]},85,obj({"授权动词":STRING}))["授权动词"].strip()
                    if intent and intent in q:
                        result.setdefault("facts",[]).extend(extract_facts(save))
                        result["write_authorization"]=intent
                return result
    options=dict(MODES)
    if not memory["versions"]["有未确认预览"]:options.pop("确认上次试排")
    if not memory["versions"]["可撤销"]:
        options.pop("撤销最近提交")
        options.pop("恢复初版")
    ctx={"已有行程天数":len(memory["days"]),"当前游客原话":q}
    turn=obj({"本轮意图简述":STRING,"主要行动":enum(options),"涉及天":{**arr(INT),"maxItems":7}})
    route=model.ask("""只判断游客说的这句话想要什么。改已经安排的某处、时间或条件属于更改原卡。
先用一句话解释当前发言的目的，再选择行为。只有明确让记住个人资料才是记录人物事实。
已排卡的站点/时刻、同行者、个人信息属于查询本会话；查询社区或报名等用公开资料。
假设用试排；明确采用展示版本才确认；撤回尚未落实的提议且要求照旧，保留当前安排。
仅说失望而没说改什么需问偏好。有多个可能对象但没有唯一指代需询问。硬性要求绝对保证但没有设施/实时数据应报告缺数据。
行程操作只填真正要安排或修改的天，保持原样的天不写。单天默认第一天。独立知识问句可与改线并存。""",ctx,250,turn)
    mode=MODES[route["主要行动"]]
    if not memory["days"] and mode in ("info","clarify"):
        deliver=model.ask("游客最终要拿到什么成品？引用攻略并要求按自己的天数、时间、取舍编排行程，属于交付自己的逐日行程；"
            "仅询问攻略写了什么或推荐看什么，属于公共问答。姓名、填表、回忆和修改文字不属于行程。",
            q,45,obj({"成品":enum(["可执行的逐日行程","公共或个人问答","其他"])}))["成品"]
        if deliver=="可执行的逐日行程":mode="plan"
    trip=None
    if mode in ("plan","edit","preview","unsupported"):
        from trip_contract import read_trip
        try:
            trip=read_trip(model,q,memory,mode)
        except ValueError as exc:
            return {"mode":"clarify","question":str(exc)}
        if trip["行动"]!="非行程" and trip["仍需核实的硬要求"]:
            return {"mode":"clarify","question":"这些条件缺少可核实的数据："+ "、".join(trip["仍需核实的硬要求"])}
        if mode=="unsupported" and trip["行动"]!="非行程" and trip["改动"]:
            mode={"新建":"plan","改线":"edit","试排":"preview"}[trip["行动"]]
        elif mode=="unsupported" and trip["行动"]=="非行程":
            mode="info"
    if mode=="edit" or (not memory["days"] and mode in ("plan","preview")):
        target=model.ask("判断游客真正要求交付或修改的对象。以现有攻略为底稿，按照旅行天数和可用时间取舍站点也是委托安排行程。询问文字、知识或他人说法时，即使提到地点、出发、替换等词，"
            "也不代表委托排程。游客在提供出游时段、起终点等来委托安排路线才是行程。句中明确不想规划须尊重。",
            {"原话":q,"有已确认的卡":bool(memory["days"])},105,
            obj({"对象":enum(["本次待安排的行程","游客指向的已排行程","文字表述或知识答复"])}))["对象"]
        if target=="文字表述或知识答复":mode="info"
        elif target=="游客指向的已排行程" and not memory["days"]:
            return {"mode":"clarify","question":"当前没有已确认的原行程。请确认要沿用的起终点、时间和交通条件，再为你试排。"}
        elif target=="本次待安排的行程" and mode=="edit" and not memory["days"]:mode="plan"
    if memory["versions"]["有未确认预览"] and mode not in ("info","remember","undo","restore_first"):
        selection=model.ask("已有正式行程和未确认的试排。区分读取已经展示的信息、提出全新假设和明确授权采用。"
            "只询问既有版本的时刻或内容须读取，不重算。其他咨询、改线或还原不属于采用。",q,80,
            obj({"本轮授权":enum(["查询已有备选或比较两个版本","正式采纳现有备选","其他任务或提出新条件"])}))["本轮授权"]
        if selection=="查询已有备选或比较两个版本":mode="inspect_preview"
        elif selection=="正式采纳现有备选":mode="confirm_preview"
        elif mode=="confirm_preview":mode="clarify"
    if memory["days"] and mode in ("info","recall","keep"):
        ownership=model.ask("设想两位游客各有不同的已确认行程。这里是否只是在问说话者自己原来排好的站点、时段或必须保留的条件，"
            "回答必须读其原卡？介绍站点的公共属性、推荐哪些地方值得去、问比赛规则都不属于只读原卡。",
            {"完整来意":q},60,obj({"取证范围":enum(["只询问本游客原有行程","含独立公共事实或另有操作"])}))["取证范围"]
        if ownership=="只询问本游客原有行程":
            return {"mode":"info","question":"","tools":[],"reads":[q],"facts":[],"days":[],"unsupported":[]}
    if split_tasks and mode in ("remember","info","recall","clarify"):
        composed=split_memory_public()
        if composed:return composed
    if mode=="recall":
        scope=model.ask("判断问题的答案最终来自哪里。先前聊过一个概念而现在问该概念的定义、出处或事实，仍需公开资料。"
            "问同行者、本人既有约定或已排路线则属于个人会话，即使记忆里找不到答案也不要去搜公开资料。",
            {"游客问题":q},65,obj({"信息来源":enum(["公开资料","个人会话"])}))
        if scope["信息来源"]=="公开资料":mode="info"
    if mode=="remember":
        speech=model.ask("判断游客是否在陈述可保存的新事实，还是向你询问之前的记录。提问不能作为新的记忆依据。",
            {"原话":q},60,obj({"言语行为":enum(["提供或纠正个人资料","询问已有记录"])}))["言语行为"]
        if speech=="询问已有记录":mode="recall"
    if mode=="edit":
        authorize=model.ask("最后的决定是否要求实际调整已确认行程？如果游客撤回尚未生效的提议、明确说采用原安排，就选维持原卡。明确只改某项并要求其他照旧则选执行修改。",
            {"游客原话":q},65,obj({"决定":enum(["执行修改","维持原卡"])}))
        if authorize["决定"]=="维持原卡":mode="keep"
    s={"mode":mode,"question":"","tools":[],"reads":[],"facts":[],"days":[],"unsupported":[]}
    if mode=="inspect_preview":
        return s
    if mode=="recall":
        also_public=model.ask("除回忆已有约定或个人资料外，本轮是否还问了独立的公共事实？",
            q,35,obj({"还有公共问题":{"type":"boolean"}}))["还有公共问题"]
        if also_public:mode=s["mode"]="info"
    if mode in ("confirm_preview","undo","restore_first","keep","recall","remember"):
        if mode=="remember":
            s["facts"]=extract_facts(q)
            if not s["facts"]:s["reads"]=[q]
        if mode in ("keep","recall","remember"):
            s["mode"]="info"
            if mode=="keep":s["question"]="沿用当前已确认的行程。"
            if mode=="recall":s["reads"]=[q]
        return s
    # One obligation per answerable question. Private context stays inside the session.
    requests_external=mode=="info" or model.ask("游客在当前行程要求之外，是否明确还要求回答一个公共知识问题？只提到地名或行程主题时填false。",
        {"本轮":q},40,obj({"yes":{"type":"boolean"}}))["yes"]
    jobs=[]
    if requests_external:
        raw=model.ask("逐字摘录游客实际提问的各个独立问题（含询问个人记录），不改变措辞，不增加相关问题。多问分别摘取。"
            "背景陈述和行程修改不要摘。",{"游客原文":q},280,QUESTIONS)["独立知识问题"]
        jobs=[part.strip() for part in raw if part.strip() and part.strip() in q]
        # A paraphrased or omitted clause must not disappear when a different clause matched.
        # Keep its original text as an obligation; the model still decides if it needs a tool.
        for sentence in re.split(r"(?<=[。！？?！；;])",q):
            sentence=sentence.strip()
            if not sentence or any(sentence in part for part in jobs):
                continue
            matched=sorted({part for part in jobs if part in sentence},key=len,reverse=True)
            if not matched:
                jobs.append(sentence)
                continue
            # Passing one verbatim extraction does not cover the rest of a compound sentence.
            fragments=re.split("|".join(re.escape(part) for part in matched),sentence)
            remaining=[s.strip(" ，,。！？?!；;") for s in fragments if re.search(r"\w",s)]
            if remaining:
                indices=model.ask("下面是原句中尚未分配的片段。哪几段另外请求了一个有独立答案的事实或已存信息？"
                    "选原文编号。纯背景、主语、连词、语气和回答格式不选。答案未知也算请求。",
                    {"完整原句":q,"已分配的问题":matched,"未分配片段":dict(enumerate(remaining,1))},
                    75,obj({"另有提问":arr(enum([str(i) for i in range(1,len(remaining)+1)]))}))["另有提问"]
                jobs.extend(remaining[int(i)-1] for i in dict.fromkeys(indices))
    for query in dict.fromkeys(jobs or ([q] if mode=="info" else [])):
        if mode in ("plan","edit","preview","clarify","unsupported","conflict"):
            standalone=model.ask("仅判断这段原文的言语行为。游客是在向接待员请求一个外部事实，还是在说明行程要求、背景或偏好？",
                query,55,obj({"行为":enum(["查询外部事实","给出安排要求或说明"])}))["行为"]
            if standalone!="查询外部事实":continue
        topic=model.ask("找出当前片段在问哪个实体的什么属性，给出资料类型和可独立作答的检索问题。"
            "地点和机构是什么关系、在那里从事什么活动应查机构；只有问怎么走、地址或坐标才查位置。"
            "先确定当前片段的主体，再按主体所在领域选择资料。定义、全称、由来等问法可以出现在任何领域。"
            "SPU资料介绍数命SPU本身及其成员承担的责任；社区运营及教学查社区。"
            "完整原话中的其他独立问题各自分流，不能改变本片段的领域。"
            "背景、表达感受、索要出处等无独立事实问题时选最后一类。保留原意，结合原话与前一轮补全代词，勿添加原文未问的事项。",
            {"前一轮问答":memory["recent"][-1] if memory["recent"] else {},
             "完整原话":q,"当前片段":query},200,TOPIC)
        name=TOOLS_BY_PURPOSE[topic["资料类型"]]
        assertion=None
        if name is None:
            context={"游客完整原话":q,"待判断片段":query,"上轮问答":memory["recent"][-1] if memory["recent"] else {}}
            intent=model.ask("只判断言语行为。游客是在要求核实一个具体说法的真伪或有无出处，还是仅提供背景和格式？"
                "未知和错误的说法同样可以被要求核实。",context,55,
                obj({"行为":enum(["要求核实所指说法","仅背景或回复方式"])}))
            if intent["行为"]=="要求核实所指说法":
                result=model.ask("补全该片段所指的主体和完整待核实主张，保留数量、限定词。选择应查询的领域，无论最后能否查到。",
                    context,145,obj({"主张":STRING,"领域":enum([k for k,v in TOOLS_BY_PURPOSE.items() if v not in (None,"memory","location")])}))
                assertion=result["主张"] or query
                name=TOOLS_BY_PURPOSE[result["领域"]]
                topic["独立检索问题"]="资料是否证实以下说法？"+assertion
        if name=="memory":
            reading=model.ask("这段话是否要求读出一个已保存的事实？仅要求保持现状、不改路线属于操作说明，答否。",
                query,40,obj({"需要读回":{"type":"boolean"}}))["需要读回"]
            if reading:s["reads"].append(query)
        elif name:
            job={"name":name,"query":topic["独立检索问题"] or query,"source_query":query}
            if name=="location":
                job["context_query"]=q
            if assertion:
                job["assertion"]=assertion
                job["context_query"]=q
            s["tools"].append(job)
    original="、".join(name for card in memory["days"].values() for name in card["order"])
    if mode in ("unsupported","conflict","clarify"):
        s["mode"]="clarify"
        if mode=="unsupported":
            s["question"]="现有资料无法核实并保证你要求的条件："+q
        elif mode=="conflict":
            s["question"]="这两项要求互相冲突："+q+" 你想放宽其中哪一项？"
        else:
            s["question"]="你希望调整时间、游览节奏，还是具体哪一站？"+("原卡上的站点有"+original+"。" if original else "")
        return s
    if mode in ("plan","edit","preview"):
        from quantities import NUM,number
        day_refs=lambda fragment:list(dict.fromkeys(number(n) for n in re.findall(rf"第({NUM})[天日]",fragment)))
        labels=list(dict.fromkeys(re.findall(r"(?:星期|礼拜|周)[一二三四五六日天]|(?:\d{4}年)?\d{1,2}月\d{1,2}[日号]",q)))
        assignments={}
        if labels:
            prior={k:v.get("calendar_label") for k,v in memory["days"].items() if v.get("calendar_label")}
            if mode=="plan" or prior:
                dates=model.ask("把点名的实际出游日期对齐到行程序号。星期几不是第几天。单日游是第1天；"
                    "多日游用出游的先后顺序，修改时只使用已有日历对应关系。仅作为背景提及或无法对应的日期不填。",
                    {"原话":q,"日历原词":labels,"已存日期":prior},135,
                    obj({"对应":arr(obj({"日历":enum(labels),"旅行第几天":{"type":"integer","minimum":1,"maximum":7}}))}))["对应"]
                assignments={v["日历"]:v["旅行第几天"] for v in dates}
            if mode!="plan" and len(memory["days"])>1 and not assignments and not day_refs(q):
                return {**s,"mode":"clarify","question":"这次说的日期对应原行程的第几天？"}
        explicit=day_refs(q)
        if mode=="plan" and trip:
            days=list(range(1,trip["天数"]+1))
        elif explicit:
            days=list(dict.fromkeys(route["涉及天"]+explicit))
            if mode!="plan":days=[d for d in days if str(d) in memory["days"] or d in explicit]
        elif mode=="plan":
            count=model.ask("游客本次实际要规划几天？周几、月份、几号不代表行程日序。只计划一个游玩日就填1。",q,50,
                obj({"天数":{"type":"integer","minimum":1,"maximum":7}}))["天数"]
            days=list(range(1,count+1))
        elif assignments:
            days=list(dict.fromkeys(assignments.values()))
        elif len(memory["days"])==1:
            days=[int(next(iter(memory["days"])))]
        else:
            days=list(dict.fromkeys(route["涉及天"])) or [1]
        trip_changes=(trip or {}).get("改动",[])
        lodging_only=False
        lodging=[v for v in trip_changes if v["字段"]=="住宿锚点" and v["操作"]=="设置"]
        if mode in ("edit","preview") and lodging and memory["days"]:
            binding=model.ask("确认住宿变更的范围。更换某晚住处，连带当天回程和次晨集合，"
                "即使新住宿与某个景点同名，也不是替换游览站。保持原有游览站不是新增游览要求。"
                "选出要换住处的夜晚（日序为当晚，不含只是从住处出发的次晨）。",
                {"本轮原话":q,"已有行程":memory["days"]},130,obj({"入住夜晚":arr({"type":"integer","enum":[int(k) for k in memory["days"]]}),
                "其他事项":enum(["仅住宿及对应接驳，余下照旧","另外变更游览站点、时段或其他要求"])}))
            nights=list(dict.fromkeys(binding["入住夜晚"]))
            if not nights:return {**s,"mode":"clarify","question":"你要改哪一晚的住宿？","days":[]}
            same_place=len({item["值"] for item in lodging})==1
            lodging_only=binding["其他事项"]=="仅住宿及对应接驳，余下照旧" and same_place
            if same_place:
                best=next((item for item in lodging if item["值"] in item["原文"]),lodging[0])
                best["日期"]=nights
                trip_changes=[item for item in trip_changes if item["字段"]!="住宿锚点" or item is best]
            if lodging_only:days=nights
        if mode!="plan":
            days=list(dict.fromkeys(days+[d for item in trip_changes for d in item["日期"]]))
        texts={day:q for day in days}
        if len(days)>1:
            fragments=[v.strip() for v in re.split(r"[，。；！？!?;,]",q) if v.strip()]
            grouped={day:[] for day in days}
            by_id={str(i):fragment for i,fragment in enumerate(fragments)}
            scopes=model.ask("按叙事顺序，以整段行程的实际旅行日序给每个片段分配日期。解出次日、翌日、隔天、最后一天等相对于前文的指代。"
                "共同指令给每个适用日。只说几日游、只说保持某日不动可给空数组。只说日期但未描述事项可以作为下文日期锚点。"
                "同一句有实际安排的片段不能遗失。返回各片段的编号和适用旅行日序。",{"原文":q,"日期":days,"原文片段":by_id},
                800,obj({"范围":arr(obj({"编号":enum(by_id),"日期":arr({"type":"integer","enum":days})}))}))["范围"]
            mapped={by_id[row["编号"]]:list(dict.fromkeys(row["日期"])) for row in scopes}
            active=[]
            for fragment in fragments:
                explicit=day_refs(fragment) or [d for label,d in assignments.items() if label in fragment]
                if explicit:active=explicit
                if fragment in mapped and not mapped[fragment]:continue
                selected=explicit or mapped.get(fragment) or active or days
                active=selected
                for d in selected:grouped[d].append(fragment)
            texts={d:"，".join(parts) for d,parts in grouped.items()}
        for day in days:
            day_text=texts[day]
            scoped=[item for item in trip_changes if day in item["日期"]]
            # The date-to-day assignment and mobility contract must refer to the same date.
            for label,assigned in assignments.items():
                full=re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})[日号]",label)
                if assigned==day and full:
                    from datetime import date
                    iso=date(*map(int,full.groups())).isoformat()
                    scoped=[item for item in scoped if item["字段"]!="出行日期"]
                    scoped.append({"日期":[day],"对象":"","字段":"出行日期","值":iso,"操作":"设置","原文":label})
            if not day_text and mode!="plan" and not scoped: continue
            op,err=day_patch(model,day_text,day,memory["days"].get(str(day),{}),validate_op,mode) if day_text and not lodging_only else (None,"")
            if err:
                return {**s,"mode":"clarify","question":err,"days":[]}
            if op is None and (mode=="plan" or scoped):
                op={"day":day,"query":day_text or q,"set":{}}
            if op is not None:
                from trip_contract import mobility_for
                old_card=memory["days"].get(str(day),{})
                op["mobility"]=mobility_for(old_card.get("contract",{}).get("mobility",{}),scoped,day)
                if mode=="plan" and day in (trip or {}).get("明确只游半天的日期",[]) and not ({"end","max_minutes"} & op["set"].keys()):
                    op["set"]["max_minutes"]=240
                    op["mobility"]["duration_assumption"]="按半日游预留4小时"
                edges=[(e["先"],e["后"]) for e in (trip or {}).get("指定游览先后",[]) if e["日"]==day]
                if edges:
                    op["mobility"]["visit_order"]=[list(pair) for pair in edges]
                    op["require"]=list(dict.fromkeys([*op.get("require",[]),*(n for pair in edges for n in pair)]))
                if old_card and scoped and not any(op.get(k) for k in ("set","add","remove","require","unrequire","exclude","replacements")):
                    consent=model.ask("游客是否明确授权为了新的交通或同行条件删去原来游览的站点？只调整预算、方式、人数、试算或说其他照旧，都不授权删站。",q,45,obj({"授权删站":{"type":"boolean"}}))
                    if not consent["授权删站"]:op["add"]=list(old_card["order"])
                if mode=="plan" and trip and trip["攻略"]!="组合":
                    from trip_contract import GUIDES
                    template=next(g for g in GUIDES if g["id"]==trip["攻略"])
                    if len(template["days"])==trip["天数"]:
                        op["template"]=template["id"]
                        op["strict_template"]=trip["必须按原站序完整保留"]
                    elif trip["必须按原站序完整保留"]:
                        return {**s,"mode":"clarify","question":"原版攻略天数与可用天数不同，可以节选其中几天吗？","days":[]}
                if mode=="plan":
                    for label,numbered in assignments.items():
                        if numbered==day or (len(labels)==1 and len(days)==1):
                            op["calendar_label"]=label
                            break
                s["days"].append(op)
        if not s["days"] and mode=="edit":
            s.update(mode="info",question="沿用当前已确认的行程。")
    return s
