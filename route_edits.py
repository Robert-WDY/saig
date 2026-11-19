"""Apply map controls to the authoritative itinerary in the visitor's session."""
from copy import deepcopy
import json

from deliverables import check_days, choose
from places import PLACES
from planning import Invalid, solve, transport_cache
from storage import Conflict


def editable_places():
    return sorted(name for name, place in PLACES.items() if place["minutes"])


def edit_route(store, sid, request_id, change):
    key = "map:" + request_id
    question = json.dumps(change, ensure_ascii=False, sort_keys=True)
    revision, state, cached = store.read(sid, key, question)
    if cached is not None:
        return cached
    option_id, day = change.get("plan"), change.get("day")
    if not isinstance(option_id, str) or not isinstance(day, str):
        raise Invalid("请选择要修改的方案和日期。")
    option = state.get("options", {}).get(option_id)
    if option_id == "current":
        days = state["days"]
    elif option_id == "preview":
        days = state.get("pending_days", {})
    else:
        days = option["days"] if option else {}
    if day not in days:
        raise Conflict("这份路线已失效，请回接待台查看当前方案。")
    old = days[day]
    if change.get("basis") != {"order": old["order"], "contract": old["contract"]}:
        raise Conflict("这天的行程已经变更。请在接待台重新查看最新行程后再编辑。")
    add, remove = change.get("add"), change.get("remove")
    for names in (add, remove):
        if not isinstance(names, list) or len(names)>12 or any(not isinstance(n,str) or n not in PLACES or not PLACES[n]["minutes"] for n in names):
            raise Invalid("请选择目录中的游览站点。")
        if len(set(names)) != len(names):
            raise Invalid("同一站点重复。")
    prior = old["order"]
    if not (add or remove) or set(add) & set(prior) or not set(remove) <= set(prior):
        raise Invalid("请检查新增或移除的站点。")
    c = deepcopy(old["contract"])
    if set(remove) & {c["origin"], c["destination"]}:
        raise Invalid("出发与抵达地点绑定了时间约定，请在接待台修改。")
    if set(add) & set(c["exclude"]):
        raise Invalid("新增站点与原有排除条件冲突，原行程已保留。")
    survivors = [n for n in prior if n not in remove]
    if not survivors and not add:
        raise Invalid("每天至少保留一个游览站点。")
    c["must"] = [n for n in c["must"] if n not in remove] + [n for n in add if n not in c["must"]]
    revised = deepcopy(days)
    token = transport_cache.set({})
    try:
        order, audit = solve(c,prior,[],add=survivors+add,remove=remove,old_stops=old["audit"]["stops"])
        card = revised[day]
        old_stops = {s["place"]:s for s in old["audit"]["stops"]}
        card.update(contract=c,order=order,audit=audit,diff={"added":add,"removed":remove,
            "retimed":[s["place"] for s in audit["stops"] if s["place"] in old_stops and s!=old_stops[s["place"]]]})
        if template := card.get("template"):
            source = template["source_order"]
            template.update(skipped=[n for n in source if n not in order],added=[n for n in order if n not in source])
            template.pop("adaptation",None)
            if not set(source)&set(order):
                template["adaptation"]="本日已按地图编辑重排"
        if "replacement_evidence" in card:
            card["replacement_evidence"] = [v for v in card["replacement_evidence"] if v["place"] in order]
        check_days(revised,len(days),days,[int(day)])
    finally:
        transport_cache.reset(token)
    if option_id == "current":
        choose(state,revised)
    elif option_id == "preview":
        state["pending_days"] = revised
    else:
        option.update(days=revised,version=option.get("version",1)+1)
        option.pop("answer",None)
    title = option["title"] if option else ("正式行程" if option_id=="current" else "试排方案")
    changes = "，".join(s for s in ("添加"+"、".join(add) if add else "", "移除"+"、".join(remove) if remove else "") if s)
    action = f"地图编辑《{title}》第{day}天：{changes}"
    answer = "重排后："+" → ".join(order)+"。"
    state["turns"] = (state["turns"]+[{"user":action,"answer":answer,"offered_places":[],"sources":[]}])[-12:]
    result = {"cards":revised,"version":option["version"] if option else revision+1,"action":action,"answer":answer}
    return store.save(sid,key,question,revision,state,result)
