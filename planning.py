"""Planning and acceptance share the same frozen Day contract and evaluator."""
from collections import Counter
from copy import deepcopy
from itertools import combinations
from places import PLACES, region
from time import monotonic
from limits import TurnExpired, remaining
from contextvars import ContextVar
from transport import choose
from trip_contract import settings

transport_cache=ContextVar("transport_cache",default=None)

BASE = {"start":540,"end":1080,"origin":None,"destination":None,"buffer":0,"must":[],
        "exclude":[],"durations":{},"windows":{},"regions":[],"max_stops":12,"max_minutes":1440}
FIELDS = set(BASE)
REGIONS = ("汉口","武昌","汉阳")


class Invalid(ValueError):
    pass


def minutes(value, maximum=1439):
    if type(value) is not int or not 0 <= value <= maximum:
        raise Invalid("时间字段需要有效的整数分钟")
    return value


def validate(c):
    if set(c)-{"mobility"}!=FIELDS:
        raise Invalid("未知或缺失行程约束")
    if "mobility" in c:
        try:
            settings(c["mobility"])
        except (KeyError,TypeError,ValueError) as exc:
            raise Invalid("同行条件无效："+str(exc)) from exc
    for k in ("start","end","buffer"):
        minutes(c[k])
    if c["buffer"] and not c["destination"]:
        raise Invalid("返程余量必须绑定到目的地")
    for k in ("origin","destination"):
        if c[k] is not None and c[k] not in PLACES:
            raise Invalid(f"位置尚未核实：{c[k]}")
    for k in ("must","exclude"):
        if not isinstance(c[k],list) or any(n not in PLACES or not PLACES[n]["minutes"] for n in c[k]):
            raise Invalid(f"无法核查地点约束 {k}")
    if set(c["must"]) & set(c["exclude"]):
        raise Invalid("同一地点同时必去和排除")
    if not isinstance(c["regions"],list) or any(r not in REGIONS for r in c["regions"]):
        raise Invalid("可审核的路线片区为汉口、武昌、汉阳")
    if type(c["max_stops"]) is not int or not 1<=c["max_stops"]<=12:
        raise Invalid("单日可审核的游览数量为1到12站")
    if not minutes(c["max_minutes"],1440):
        raise Invalid("游览时间预算必须为正数")
    for n,v in c["durations"].items():
        if n not in PLACES or not minutes(v,720):
            raise Invalid("无效的游览时长")
    for n,w in c["windows"].items():
        if n not in PLACES or not isinstance(w,list) or len(w)!=2 or minutes(w[0])>minutes(w[1]):
            raise Invalid("无效的访问窗口")


def evaluate(c, order):
    validate(c)
    if len(order)!=len(set(order)) or any(n not in PLACES or not PLACES[n]["minutes"] for n in order):
        raise Invalid("站点重复或无法规划")
    t,previous = c["start"],c["origin"]
    violations = []
    visits = []
    legs=[]
    cache=transport_cache.get()
    if cache is None:cache={}
    def travel(a,b,minute):
        if not a or not b:return 0
        try:
            leg=choose(a,b,c.get("mobility", {"rules":[]}),minute,cache)
        except ValueError as exc:
            violations.append(str(exc))
            return 0
        legs.append(dict(departure=minute,**leg))
        return leg["minutes"]
    for n in order:
        leg = travel(previous,n,t)
        t += leg
        window = c["windows"].get(n,[0,1439])
        start = max(t,window[0])
        finish = start+c["durations"].get(n,PLACES[n]["minutes"])
        if finish>window[1]:
            violations.append(f"{n}超出访问窗口")
        visits.append(dict(place=n,leg=leg,start=start,end=finish))
        t,previous=finish,n
    last_leg = travel(previous,c["destination"],t)
    arrival = t+last_leg
    if arrival+c["buffer"]>c["end"]:
        violations.append(f"最晚时间超出 {arrival+c['buffer']-c['end']} 分钟")
    if arrival+c["buffer"]-c["start"]>c["max_minutes"]:
        violations.append("超过当日时间预算")
    for n in c["must"]:
        if n not in order:
            violations.append(f"缺少必去点 {n}")
    if set(order)&set(c["exclude"]):
        violations.append("包含排除地点")
    if len(order)>c["max_stops"]:
        violations.append("超过每日最多游览站数")
    for n in order:
        if c["regions"] and region(n) not in c["regions"]:
            violations.append(f"{n}不在指定片区")
    if not order:
        violations.append("当天无游览站点")
    proof=dict(legs=legs,stops=visits,arrival=arrival,last_leg=last_leg,buffer=c["buffer"],violations=violations)
    if "mobility" in c:
        values=settings(c["mobility"])
        for before,after in c["mobility"].get("visit_order",[]):
            if before in order and after in order and order.index(before)>order.index(after):
                violations.append(f"游览顺序要求{before}先于{after}")
        bound=sum(l["fare_bound"] for l in legs) if all(l["fare_bound"] is not None for l in legs) else None
        if not legs and any(k in values for k in ("交通方式","单段步行上限米","每日全团交通预算元","全程全团交通预算元")):
            violations.append("缺少可核验的转场，请提供集合点或第二个游览点")
        if "每日全团交通预算元" in values and (bound is None or bound>values["每日全团交通预算元"]):
            violations.append("超过每日全团交通预算或缺少确定价格")
        proof.update(legs=legs,group_fare_bound=bound)
    return proof


def guide_candidates(retrieved, required):
    result=[]
    for row in retrieved:
        if row["id"]=="city-2020" or row["id"].startswith(("book.202.","book.203.")):
            # These source pages interleave several dates. Use the day records indexed beside them.
            continue
        if row.get("day_order"):
            names=row["day_order"]
            result.append((len(set(required)&set(names)),row["id"],names))
            continue
        positions = sorted((row["text"].index(n),n) for n,p in PLACES.items()
                           if p["minutes"] and n in row["text"])
        if positions:
            names=[n for _,n in positions]
            result.append((len(set(required)&set(names)),row["id"],names))
    return sorted(result,key=lambda x:-x[0])


def solve(c, prior, guide_order, add=(), remove=(), old_stops=(), replacements=(), preserve_guide_order=False):
    """Preserve relative order of surviving old stops. Minimize deleted/added objects first."""
    validate(c)
    required=list(dict.fromkeys(c["must"]+list(add)))
    if set(required)&set(remove):
        raise Invalid("指定删除的地点仍为必去点")
    pool=list(dict.fromkeys((prior if prior else guide_order)+required))
    pool=[n for n in pool if n not in remove and n not in c["exclude"]]
    if len(pool)>12:
        raise Invalid("单日候选地点过多，请分天安排")
    # New mandatory stops can be inserted at any slot, without reordering existing objects.
    initial=[n for n in pool if n not in required or n in prior or n in guide_order]
    missing=[n for n in pool if n not in initial]
    # When editing, newly requested stops must be tested at all insertion points.
    if prior:
        initial=[n for n in pool if n in prior]
        missing=[n for n in pool if n not in prior]
    if len(missing)>4:
        raise Invalid("一次新增的必去点过多，请拆分行程")
    deadline = monotonic() + remaining(8)
    def check_time():
        if monotonic() >= deadline:
            raise TurnExpired("本次路线搜索超时，请减少单日候选地点后重试。")
    def insert(order, rest):
        check_time()
        if not rest:
            yield order
            return
        for i in range(len(order)+1):
            yield from insert(order[:i]+[rest[0]]+order[i:],rest[1:])
    best=None
    reason=Counter()
    old_times={s["place"]:s["start"] for s in old_stops}
    if len(required)>c["max_stops"]:raise Invalid("超过每日最多游览站数")
    for size in range(min(len(initial),c["max_stops"]-len(missing)),-1,-1):
        for seq in combinations(initial,size):
            if not set(required).issubset(set(seq)|set(missing)):
                continue
            variants=[]
            for proposed in insert(list(seq),missing):
                variants.append(proposed)
                if not prior and not preserve_guide_order and c.get("mobility") and len(proposed)>2:
                    groups=list(dict.fromkeys(region(n) for n in proposed))
                    if c["origin"] and region(c["origin"]) in groups:
                        groups.sort(key=lambda g:g!=region(c["origin"]))
                    clustered=sorted(proposed,key=lambda n:groups.index(region(n)))
                    if clustered!=proposed:variants.append(clustered)
            for order in variants:
                check_time()
                edges=c.get("mobility",{}).get("visit_order",[])
                if edges and not preserve_guide_order:
                    pending=list(order)
                    ordered=[]
                    while pending:
                        ready=next((n for n in pending if not any(b==n and a in pending for a,b in edges)),None)
                        if ready is None:break
                        pending.remove(ready)
                        ordered.append(ready)
                    if not pending:order=ordered
                verification=evaluate(c,order)
                if verification["violations"]:
                    reason.update(verification["violations"])
                    continue
                diff=len(set(prior)^set(order))
                moved=sum(abs(s["start"]-old_times[s["place"]]) for s in verification["stops"] if s["place"] in old_times)
                shifted=sum(abs(order.index(new)-prior.index(old)) for old,new in replacements)
                rank=(diff if prior else -len(order),shifted,moved,verification["arrival"])
                if best is None or rank<best[0]:
                    best=(rank,order,verification)
        if best:
            break
    if not best:
        detail="、".join(v for v,_ in reason.most_common(3))
        raise Invalid("当前约束无法排出可行行程："+(detail or "可用站点不足"))
    return best[1],best[2]


def new_contract():
    return deepcopy(BASE)
