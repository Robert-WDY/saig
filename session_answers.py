"""Session-only evidence. The model selects records; the displayed values come from storage."""
import re
from quantities import NUM,number
from semantics import arr, obj, enum, STRING

def clock(n):
    return f"{n//60:02d}:{n%60:02d}"

def evidence(state):
    rows={}
    for index,f in enumerate(state["facts"]):
        who={"self":"你","self.mother":"你的妈妈"}.get(f["subject"],f["subject"])
        relation={"name":"姓名","likes":"喜好","stays_at":"住处"}.get(f["relation"],f["relation"])
        rows[f"fact/{index}"]=f"{who}的{relation}是{f['object']}。"
    for day,card in state["days"].items():
        prefix=f"第{day}天"
        key=f"day/{day}"
        c=card["contract"]
        rows[key+"/order"]=prefix+"的游览顺序是"+" → ".join(card["order"])+"。"
        rows[key+"/must"]=prefix+"的必去地点："+("、".join(c["must"]) or "未指定")+"。"
        rows[key+"/time"]=f"{prefix}可用时段为{clock(c['start'])}至{clock(c['end'])}。"
        for field,label in (("origin","出发地"),("destination","必须抵达的终点")):
            if c[field]:rows[key+"/"+field]=prefix+"的"+label+"是"+c[field]+"。"
        for i,stop in enumerate(card["audit"]["stops"],1):
            name=stop["place"]
            label=f"第{i}站"+("（最后一站）" if i==len(card["order"]) else "")
            rows[key+"/stop/"+str(i)]=f"{prefix}{label}是{name}，{clock(stop['start'])}至{clock(stop['end'])}，停留{stop['end']-stop['start']}分钟。"
        for i,leg in enumerate(card["audit"].get("legs",[]),1):
            if leg.get("directions") and leg["origin"]!=leg["destination"]:
                arrival=leg["departure"]+leg["minutes"]
                rows[f"{key}/leg/{i}"]=f"{prefix}从{leg['origin']}到{leg['destination']}：{leg['directions']}。预计{clock(arrival)}抵达。"
    return rows

def recall(model,question,state):
    rows=evidence(state)
    if rows:
        requested=model.ask("逐字摘录要从已有记录中回答的每个子问题。不同人物或属性可以分开；不摘背景或保持行程不动的指令。"
            "不要扩写用户没问的内容。",question,130,obj({"问题":{**arr(STRING),"maxItems":5}}))["问题"]
        parts=list(dict.fromkeys(s.strip() for s in requested if s.strip() and s.strip() in question))
        for clause in re.split(r"[，,。；;！？!?]",question):
            if clause.strip() and not any(clause.strip() in p or p in clause.strip() for p in parts):
                parts.append(clause.strip())
        parts=parts or [question]
        keys=[]
        for part in parts:
            days=[str(number(s)) for s in re.findall(rf"第({NUM})[天日]",part)]
            candidates={k:v for k,v in rows.items() if not days or not k.startswith("day/") or k.split("/")[1] in days}
            selected=model.ask("从当前子问逐一确认需要回答的人物属性或日期字段，为每项选择直接对应的记录。"
                "同一子问可能同时索要姓名和喜好。仅背景或资料不足就返回空数组。不要添加无关属性。",
                {"已确认记录":candidates,"完整问题":question,"当前子问":part},100,obj({"记录":arr(enum(candidates))}))["记录"] if candidates else []
            keys.extend(k for k in selected if k in candidates and k not in keys)
        if keys:return "\n".join(rows[k] for k in keys),keys
    return "当前会话没有可确认的这项记录。",[]
