"""Local hybrid index. Category filters come from explicit tool calls or the model."""
from collections import Counter
import json
import math
from pathlib import Path
import re
import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

DATA = Path(__file__).resolve().parent / "data"
# Section headings for the official DOCX, whose paragraphs otherwise all share a file title.
HEADINGS = {"spu.5.1":"数命 SPU 术语释义 名词解释 概念 定义 是什么意思 中文 英文 全称",
    "spu.6.1":"五项能力总览","spu.7.1":"独立判断","spu.8.1":"调用AI工具","spu.9.1":"组织任务与资源",
    "spu.10.1":"完成交付与验收","spu.11.1":"承担责任与纠错","spu.12.1":"人的决断力与AI能力",
    "spu.14.1":"数命科技内部实践","spu.15.1":"人才培养和创业",
    "community.3.1":"社区是什么 建设运营 场地布局","community.4.1":"真实订单如何交付",
    "community.5.1":"AI工坊","community.6.1":"规划中的体验区","community.7.1":"学员入门 订单带教",
    "community.8.1":"供需对接","community.9.1":"创业孵化","community.10.1":"智民里街区规划"}


def tokens(text):
    words = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", text.lower())
    result = []
    for word in words:
        if word.isascii():
            result.append(word)
        else:
            result.extend(word)
            result.extend(word[i:i+2] for i in range(len(word)-1))
    return result


class Knowledge:
    def __init__(self, curated=None):
        self.curated = curated if curated is not None else json.loads((DATA/"official.json").read_text(encoding="utf8"))
        self.rows = list(self.curated)
        from places import ATLAS, GATEWAYS
        network = json.loads((DATA/"metro_lines.json").read_text(encoding="utf8"))
        access = []
        for hub, station in GATEWAYS.items():
            lines = [name for name, stops in network["lines"].items() if station in stops]
            if lines:
                access.append(f"{hub}对应地铁站「{station}」，线路有{'、'.join(lines)}。")
        self.rows.append(dict(id="metro_lines.json", category="wuhan", title="武汉铁路枢纽与机场的地铁接驳",
                              text="".join(access), locator="武汉线路图 · 枢纽站名", source=network["source"],
                              edition="线路图核对 "+network["checked"]))
        for place in ATLAS:
            if "official_name" in place:
                self.rows.append(dict(id=place["id"], category="attraction", title=place["official_name"]+" · 名录",
                    text=f'{place["name"]}收录于{place["official_name"]}，名录等级 {place["grade"]}。地点：{place["address"]}。'+place.get("notice",""),
                    locator=place["official_name"], source=place["official_source"], edition="名录核对 2026-11-19"))

        self.rows.extend(json.loads(s) for s in (DATA/"handbooks.jsonl").read_text(encoding="utf8").splitlines())
        from trip_contract import GUIDES,CITY_SOURCE
        refs={r["id"]:r for r in self.rows}
        overview={"id":"city-2020","title":"打卡大武汉旅游线路","source":CITY_SOURCE,
                  "category":"guide","edition":"武汉市文旅局 2020-08-12","locator":"半日、二日游线路",
                  "text":"武昌古城游含户部巷、黄鹤楼、辛亥革命博物馆和昙华林。古今风情都市游分两天游览汉阳、汉口。"}
        refs[overview["id"]]=overview
        self.rows.append(overview)
        for g in GUIDES:
            for day,names in enumerate(g["days"],1):
                source=refs[g["source"]]
                day_text=" → ".join(g.get("source_days",g["days"])[day-1])
                publisher="武汉市文化和旅游局" if source["source"]==CITY_SOURCE else source["title"]
                self.rows.append({**source,"id":f"{g['id']}.day{day}","category":"guide","title":g["title"],
                    "locator":f"第{day}天（共{len(g['days'])}天）","text":f"{publisher}《{g['title']}》第{day}天的路线：{day_text}。",
                    "day_order":names,"trip_guide":g["id"],"day_index":day,"days_total":len(g["days"])})
        self.by_id = {r["id"]:r for r in self.rows}
        titles=[r["title"]+" "+HEADINGS.get(r["id"],"") for r in self.rows]
        docs = [t+" "+r["text"] for t,r in zip(titles,self.rows)]
        self.counts = [Counter(tokens(t)) for t in docs]
        self.titles = [set(tokens(t)) for t in titles]
        self.avg = np.mean([c.total() for c in self.counts])
        df = Counter(term for c in self.counts for term in c)
        self.idf = {term:math.log1p((len(docs)-n+.5)/(n+.5)) for term,n in df.items()}
        self.vectorizer = TfidfVectorizer(analyzer=tokens, sublinear_tf=True)
        mat = self.vectorizer.fit_transform(docs)
        self.svd = TruncatedSVD(n_components=min(80, len(docs)-1), random_state=17)
        with threadpool_limits(limits=1):
            self.dense = normalize(self.svd.fit_transform(mat))

    def search(self, query, categories=None, k=5):
        ids = [i for i,r in enumerate(self.rows) if not categories or r["category"] in categories]
        terms = set(tokens(query))
        lexical = {}
        for i in ids:
            c = self.counts[i]
            norm = 1.2*(.25+.75*c.total()/self.avg)
            lexical[i] = sum(self.idf[t]*c[t]*2.2/(c[t]+norm) for t in terms if t in c)
            lexical[i] += 4*sum(self.idf[t] for t in terms.intersection(self.titles[i]) if len(t)>1)
        q = normalize(self.svd.transform(self.vectorizer.transform([query])))[0]
        dense = self.dense @ q
        scores = Counter()
        for ranked in [sorted((i for i in ids if lexical[i]>0),key=lexical.get,reverse=True),
                       sorted((i for i in ids if dense[i]>.05),key=lambda i:dense[i],reverse=True)]:
            for pos,i in enumerate(ranked[:30],1):
                scores[i] += 1/(25+pos)
        # A direct POI/title lookup should prefer its article start over a passing mention.
        phrase=query.strip().lower()
        if len(phrase)>=2:
            for i in ids:
                r=self.rows[i]
                if r["title"].lower()==phrase or (r["id"].endswith(".1") and r["text"].lower().startswith(phrase)):
                    scores[i]+=0.09
        return [self.rows[i] for i,_ in scores.most_common(k)]


TOOLS = {"wuhan":["wuhan","attraction"], "community":["community"], "spu":["spu"],
         "saig":["saig"], "attraction":["attraction"], "food":["food"], "guide":["guide"]}


def verify_statement(model, assertion, original, evidence):
    """Independently prove each proposition, even when one instruction governs several."""
    from semantics import arr,obj,STRING
    extracted=model.ask("逐项列出实际被要求核实的独立陈述。两个不同的主体或不同属性需要分别取证时分成两条。"
        "只列当前片段质疑的断言，不把背景立项。去掉转述语，保留原话关系强度，每条只写被引说法的主语和谓词。",
        {"当前请求":original,"已消解指代的陈述":assertion},310,
        obj({"待核实陈述":{**arr(obj({"当前请求中的逐字片段":STRING,"完整主张":STRING})),"maxItems":8}}))
    statements=[]
    used=set()
    for entry in extracted["待核实陈述"]:
        fragment=entry["当前请求中的逐字片段"].strip()
        claim=entry["完整主张"].strip()
        start=original.find(fragment)
        if not fragment or not claim or start<0:continue
        span=set(range(start,start+len(fragment)))
        if not used.intersection(span):
            used.update(span)
            statements.append((claim,fragment))
    if not statements:
        return _verify_statement(model,assertion,original,evidence)
    parts=[_verify_statement(model,claim,fragment,evidence) for claim,fragment in statements]
    return {"answer":"\n".join(p["answer"] for p in parts),"supported":all(p["supported"] for p in parts),
            "citations":[c for p in parts for c in p["citations"]]}


def _verify_statement(model, assertion, original, evidence):
    from semantics import arr,enum,obj,STRING
    documents={d["id"]:d for d in evidence}
    missing={"answer":"现有资料不足以确认「"+original.strip("？?")+"」。","supported":False,"citations":[]}
    if not documents:return missing
    witness=model.ask("为游客正在质疑的具体主张寻找直接证据。分别写清待证关系、文档编号、能够单独证明或反驳这个关系的最短逐字原句。"
        "文档只介绍主体、只给整体数字或没有说到待证关系，编号选无、引文留空。禁止把游客的话当成引文。",
        {"游客待核实原句":original,"消解指代":assertion,"资料":{k:d["text"][:800] for k,d in documents.items()}},240,
        obj({"待证关系":STRING,"编号":enum(["无",*documents]),"逐字证据":STRING}))
    doc=documents.get(witness["编号"])
    quote=witness["逐字证据"].strip()
    if not doc or not quote or quote not in doc["text"]:return missing
    def measures(text):
        item=obj({"原文数量词":STRING,"统计口径":enum(["部分占整体的份额","多对象合计","单个对象或每项","其他数值"]),
                  "数值":{"type":"number"}})
        raw=model.ask("只抽取这一段文字本身明确表达的量。区分各对象所占份额、多个对象合计、单项测量。"
            "用阿拉伯数记录值，百分比和分数换算成零到一的份额。不要把地点或对象个数当作它们所占的份额。"
            "数量词逐字取原文；名称中的字、单数语法或单个实体不等于在主张数值，没有明说数量则返回空数组。",
            text,165,obj({"量":arr(item)}))["量"]
        return {(entry["统计口径"],entry["数值"]) for entry in raw
                if entry["原文数量词"] and entry["原文数量词"] in text and re.search(r"[\d零〇一二两三四五六七八九十百千万亿半%％]",entry["原文数量词"])}
    measurement=model.ask("这个具体断言要证实的是数值、份额或数量关系吗？核实成员归属、地点是否存在、词语含义属于定性事实。"
        "名称中有数字不代表要验证数量。",original,50,obj({"性质":enum(["定性事实","数量主张"])}))["性质"]
    quantities=measures(original)
    required=quantities if measurement=="数量主张" else {
        measure for measure in quantities if measure[0] in ("部分占整体的份额","多对象合计")}
    if measurement=="数量主张" and not required:return missing
    available=measures(quote) if required else set()
    if required and not {kind for kind,_ in required} <= {kind for kind,_ in available}:
        return missing
    relation=model.ask("做单条文本蕴含判断。只根据引文判断具体说法中的主语和谓词是否同时明确成立或相反。"
        "可以同真、只同主题或只证明其中一部分均选无法确定。不得补全引文没给的比例、地点或归属。",
        {"游客真正要核实的话":original,"要证明的关系":witness["待证关系"],"引文":quote},65,
        obj({"判断":enum(["从引文可推出该主张","从引文可推出相反结论","仅此引文无法确定"])}))["判断"]
    if relation=="仅此引文无法确定" or (relation=="从引文可推出该主张" and not required<=available):
        return missing
    intro="资料支持这条说法。" if relation=="从引文可推出该主张" else "这条说法与资料不符。"
    citation={**{k:doc[k] for k in ("id","source","title","locator","edition")},"quote":quote,"claim":quote}
    return {"answer":intro+quote,"supported":True,"citations":[citation]}


def grounded(model, question, evidence, original=None):
    from semantics import arr,enum,obj,STRING
    proposed=_propose(model,question,evidence)
    citations=proposed["citations"]
    asked=original or question
    if not citations:
        return {**proposed,"answer":"现有资料不足以确认「"+asked+"」，需要向相关方核实。"}
    selected=[]
    obligations={entry["question"] for entry in proposed.get("obligations", [])}
    covered=set()
    for c,subquestion in zip(citations,proposed.get("claim_questions", [question]*len(citations)),strict=True):
        scope={"实际问题":asked,"补全指代":question}
        if obligations:
            scope={"实际问题":subquestion,"原话上下文":asked}
        verdict=model.ask("判断这条引用对游客原问题的作用。原文中的主体/场所、属性及适用范围均应匹配。"
            "仅仅地址位于同一条街、出现同名词、资料所在页面相关都不足。原文只回答别的主体或属性则丢弃。"
            "直接回答其中一项、解释概念或明确回答不能保证，均可保留。",
            {**scope,"所提主张":c["claim"],"原文":c["quote"]},75,
            obj({"关系":enum(["直接回答所问事项","别的实体或属性","仅背景或不支持"])}))["关系"]
        if verdict=="直接回答所问事项":
            covered.add(subquestion)
            if c not in selected:selected.append(c)
    if not selected:
        return {"answer":"现有资料不足以确认「"+asked+"」，需要向相关方核实。","supported":False,"citations":[]}
    coverage=model.ask("只列出原问题中明确索取且现有事实尚未回答的事项，逐字摘录要求该字段的原词。"
        "按问题本身的粒度核查；询问一般机制给出运作方式就算作答，提到某类活动不代表追问具体店家、地址或更细步骤。"
        "已经给出结论或说明不能保证时勿再列。",{"原问题":asked,"事实":[c["claim"] for c in selected]},
        180,obj({"缺少的事项":arr(obj({"摘录":STRING,"字段":STRING}))}))
    missing=[entry["question"] for entry in proposed.get("obligations", []) if entry["question"] not in covered]
    for item in coverage["缺少的事项"]:
        field=item["字段"]
        if not field.strip() or not item["摘录"].strip() or item["摘录"] not in asked:continue
        resolved=model.ask("这项具体追问能否直接用已经列出的事实回答？反问、否定问法也要按逻辑理解，例如明示必需即可答能否省略。",
            {"事项":field,"明确索取该项的原词":item["摘录"],"实际问题":asked,"已有事实":[c["claim"] for c in selected]},60,
            obj({"结论":enum(["已有事实足以回答","确实未回答且游客有问","游客没有问"])}))["结论"]
        if resolved=="确实未回答且游客有问":missing.append(field.strip())
    detail=model.ask("仅查看游客问题：除了任何总体描述，游客是否还明确要求得到分别属于多个成员/分支/地点的个别取值？"
        "只有索要各成员分别的数值或明细才选逐项明细；比较不同规则、罗列推荐或只问总数覆盖谁选普通问题。",
        asked,85,obj({"范围":enum(["普通问题","索要逐项明细"]),"所问明细":STRING}))
    if detail["范围"]=="索要逐项明细":
        # An aggregate and its constituent measurements are different evidence scopes.
        facts=list(dict.fromkeys(c["claim"] for c in selected))
        totals=[]
        for fact in facts:
            scope=model.ask("按这一句自身的语义标注数量的统计单位。把多个对象加在一起得到一个数才叫合计；每个对象都有相同数值是逐项值。"
                "百分比若描述某组成部分的占比，统计对象就是该部分。",
                {"一句事实":fact},50,obj({"口径":enum(["多个对象相加的总量","各对象均适用的值","个体自己的数值或份额","未提这种数字"])}))
            if scope["口径"]=="多个对象相加的总量":totals.append(fact)
        data=model.ask("判断已证实的事实与游客所要明细的关系。只有所问的同一个量仅有多对象相加的总量、"
            "而游客还要把该数拆给各对象时才报告缺口，并选出写该总量的事实。"
            "不同对象分别给了数值，或写明每项同值，两者都有逐项依据。忽略旁及的数字。",
            {"游客问题":asked,"所问明细":detail["所问明细"],"已证实的事实":facts},240,
            obj({"关系":enum(["已有各项值或每项同值","所问量仅有合计值","不涉及这种总量拆分"]),
                 "只有总量的事实":enum(["无",*totals])})) if totals else None
        if data and data["关系"]=="所问量仅有合计值" and data["只有总量的事实"] in totals:
            missing.append(detail["所问明细"].strip() or "各对象的单独数据")
    missing=list(dict.fromkeys(missing))
    answer=list(dict.fromkeys(c["claim"] for c in selected))
    if missing:answer.append("现有资料未提供或无法确认："+"、".join(missing)+"。")
    return {"answer":"\n".join(answer),"supported":not missing,"citations":selected,"missing":missing}


def _propose(model, question, evidence):
    """Answer independent requests against the same supplied evidence, tracking each obligation."""
    if len(evidence)>1:
        raw=model.ask("逐字摘录原话中各自需要答案的独立问题。比较、辨别两种说法、一个问题的多个条件均算同一项。"
            "不许增加游客没有问的内容，背景不是问题。只有一问时返回该问本身。",{"原话":question},230,
            {"type":"object","properties":{"questions":{"type":"array","items":{"type":"string"},"maxItems":8}},
             "required":["questions"],"additionalProperties":False})["questions"]
        split=list(dict.fromkeys(s.strip() for s in raw if s.strip() and s.strip() in question))
        if len(split)>1:
            parts=[]
            for query in dict.fromkeys(split):
                choice=model.ask("选择最能回答当前小问题的材料编号。",{"问题":query,
                    "材料":[{"id":r["id"],"内容":r["text"][:550]} for r in evidence]},65,
                    {"type":"object","properties":{"id":{"type":"string","enum":[r["id"] for r in evidence]}},
                     "required":["id"],"additionalProperties":False})["id"]
                ordered=sorted(evidence,key=lambda row:row["id"]!=choice)
                parts.append(_grounded_one(model,query,ordered))
            return {"answer":"\n".join(dict.fromkeys(p["answer"] for p in parts)),
                    "citations":[c for p in parts for c in p["citations"]],"supported":all(p["supported"] for p in parts),
                    "claim_questions":[q for q,p in zip(split,parts) for c in p["citations"]],
                    "obligations":[{"question":q,"supported":p["supported"]} for q,p in zip(dict.fromkeys(split),parts)]}
    return _grounded_one(model,question,evidence)


def _grounded_one(model, question, evidence):
    """LLM selects and explains numbered source spans; the application binds the citations."""
    if len(evidence)>1 and isinstance(evidence[0]["locator"],str):
        # Fact cards for adjacent topics can share nearly all the words in a short question.
        ids=[r["id"] for r in evidence]
        rank=model.ask("按能直接回答本问题的事实（材料、时间、地点、资格等）挑一份首选依据。"
            "不要仅按话题相近来选。",{"候选":[{"id":r["id"],"原文":r["text"][:430]} for r in evidence],"问题":question},
            85,{"type":"object","properties":{"id":{"type":"string","enum":ids}},"required":["id"],"additionalProperties":False})
        evidence=sorted(evidence,key=lambda r:r["id"]!=rank["id"])
    spans={}
    for doc in evidence:
        # Reviewed fact cards keep linked qualifiers (e.g. two different deadlines) together.
        passages=[doc["text"]] if isinstance(doc["locator"],str) else re.split(r"(?<=[。！？；])",doc["text"])
        for index,line in enumerate(passages):
            if line.strip():
                spans[f"{doc['id']}#{index}"]=(doc,line.strip())
    if spans:
        sources=[{"key":k,"edition":d["edition"],"text":s} for k,(d,s) in spans.items()]
        payload={"question":question,"sources":sources}
        instruction="""仅基于所给资料直接回答游客的问题。一句能回答就只给一句。不要延伸推荐无关地点，PDF多栏连排的多个地名不能当成一个地点。
返回 {claims:[{key,text}]}，每条 text 一句话，最多3条；
key逐字取对应资料的key。优先用一条直接相关资料原句或忠实短改写。不能把“截至某日”说成“从某日起”；
报名材料中，体验网址与演示视频是两个不同的字段。对比两个概念时分别说明两边的结论与已知/待定状态，例如报名截止与点赞截止各给一句。
询问保证时只用能证实的信息；资料不够就输出空claims。"""
        schema={"type":"object","properties":{"claims":{"type":"array","maxItems":3,"items":{
            "type":"object","properties":{"key":{"type":"string","enum":list(spans)},"text":{"type":"string"}},
            "required":["key","text"],"additionalProperties":False}}},"required":["claims"],"additionalProperties":False}
        for attempt in range(2):
            # Start with the highest ranked evidence. Expand when it cannot support an answer.
            lead=evidence[:3] if isinstance(evidence[0]["locator"],int) or evidence[0].get("day_order") else evidence[:1]
            lead_ids={doc["id"] for doc in lead}
            payload["sources"]=[s for s in sources if spans[s["key"]][0]["id"] in lead_ids] if attempt==0 else sources
            schema["properties"]["claims"]["items"]["properties"]["key"]["enum"]=[s["key"] for s in payload["sources"]]
            claims=model.ask(instruction,payload,550,schema).get("claims")
            if not isinstance(claims,list) or any(not isinstance(c,dict) or c.get("key") not in spans
                    or not isinstance(c.get("text"),str) or not c["text"].strip() for c in claims):
                payload["feedback"]="所有key必须是实际来源中的完整key。"
                continue
            if not claims:
                payload["feedback"]="再次核对排名靠前的资料。能直接回答时给出原文，不足以回答才返回空数组。"
                continue
            citations=[]
            for c in claims:
                doc,quote=spans[c["key"]]
                citations.append({**{k:doc[k] for k in ("id","source","title","locator","edition")},
                                  "quote":quote,"claim":c["text"]})
            review=model.ask("""核查每个claim是否完全由相配的quote支持、是否直接回答用户。特别检查日期含义、必填与选填。如果用户同时提到两个待区分的事项，且答复只解释了其一，请指出遗漏。
返回 {ok:true} 或 {ok:false,reason:具体错误}。只支持一部分时不要批准整条。""",
                             {"question":question,"claims":citations},200)
            if review.get("ok") is True:
                return {"answer":"\n".join(c["text"] for c in claims),"citations":citations,"supported":True}
            payload["feedback"]=review.get("reason","改用引用原句回答")
        # When paraphrasing fails, let the model select one directly sufficient, verbatim passage.
        choice=model.ask("选择一处能够直接回答游客问题的完整原文。输出key；只有间接相关或没有根据时选NONE。",
                         {"来源":sources,"问题":question},80,{"type":"object","properties":{"key":{
                             "type":"string","enum":["NONE",*spans]}},"required":["key"],"additionalProperties":False})
        if choice.get("key") in spans:
            doc,quote=spans[choice["key"]]
            return {"answer":quote,"citations":[{**{k:doc[k] for k in ("id","source","title","locator","edition")},
                    "claim":quote,"quote":quote}],"supported":True}
    return {"answer":"现有资料不足以确认，建议向场馆或赛事方核实。","citations":[],"supported":False}
