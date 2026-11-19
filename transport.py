"""Compare directed travel legs. Missing price or pedestrian evidence stays unknown."""
from collections import defaultdict
from functools import lru_cache
from heapq import heappush, heappop
import json
from math import ceil, cos, hypot, radians
from pathlib import Path
import requests

from places import PLACES,ATLAS_POINTS,transit,amap_key
from diagnostics import timed
from limits import remaining
from trip_contract import settings

DATA=Path(__file__).parent/"data"
FARES="https://jtj.wuhan.gov.cn/zwgk/zfxxgkml/sfqd/202007/t20200709_1399147.shtml"
LABEL={"walk":"步行","taxi":"出租车","metro":"地铁","transit":"公交地铁","estimate":"估算转场"}
# Station associations explicitly named in the travel handbook, pp. 200–203.
ACCESS={**dict.fromkeys(("黄鹤楼","斗级营","昙华林","户部巷","粮道街"),"司门口黄鹤楼"),
        **dict.fromkeys(("江汉关","江汉路"),"江汉路"),**dict.fromkeys(("黎黄陂路","吉庆街","巴公房子","八七会议会址","中共中央机关旧址"),"大智路"),
        "汉口站":"汉口火车站","汉口江滩":"黄浦路","武汉天地":"黄浦路","东湖绿道":"梨园","东湖听涛":"梨园",
        "古琴台":"琴台","龟山公园":"琴台","万松园":"王家墩东","楚河汉街":"楚河汉街","中山公园":"中山公园",
        "武汉博物馆":"汉口火车站","光谷广场":"光谷广场","光谷空轨":"光谷四路"}

@lru_cache(maxsize=8)
def snapshot(name):
    return json.loads((DATA/name).read_text("utf8"))

@lru_cache(maxsize=512)
def metro_route(start,end):
    if not start or not end or start==end:
        return None
    data=snapshot("metro_lines.json")
    graph=defaultdict(list)
    for line,stations in data["lines"].items():
        if line not in {"1号线","2号线","3号线","4号线","5号线","6号线","7号线","8号线","11号线"}:continue
        for a,b in zip(stations,stations[1:]):
            graph[a].append((b,line))
            graph[b].append((a,line))
    queue=[(0,start,"",())]
    seen=set()
    while queue:
        cost,station,previous,hops=heappop(queue)
        if (station,previous) in seen:continue
        seen.add((station,previous))
        if station==end:return cost,hops
        for dest,line in graph[station]:
            transfer=bool(previous and previous!=line)
            path=hops+((station,line),) if previous!=line else hops
            heappush(queue,(cost+3+8*transfer,dest,line,path))
    return None

def road(a,b):
    data=snapshot("road_network.json")
    if a not in data["anchors"] or b not in data["anchors"]:return {}
    i,j=data["order"].index(a),data["order"].index(b)
    rows={}
    for mode,table in data["profiles"].items():
        length=table["metres"][i][j]
        seconds=table["seconds"][i][j]
        if length is None or seconds is None:continue
        snap=table["snap_metres"][i]+table["snap_metres"][j]
        if snap>180:continue
        rows[mode]=(ceil(length),ceil(seconds/60),snap)
    return rows

def live_transit(a,b,date,minute,cache):
    """Geocoding and scheduled multimodal options share the same provider coordinate system."""
    if not date:return []
    key=amap_key()
    if not key:return []
    def query(path,params):
        token=(path,tuple(sorted(params.items())))
        if token not in cache:
            try:
                with timed("amap/"+path) as event:
                    r=requests.get("https://restapi.amap.com/v3/"+path,params={**params,"key":key},timeout=(remaining(4),remaining(12)),allow_redirects=False)
                    r.raise_for_status()
                    d=r.json()
                    event["infocode"]=str(d.get("infocode",""))
                    event["count"]=str(d.get("count",""))
                cache[token]=d if d.get("status")=="1" else {}
            except (ValueError,requests.RequestException):
                cache[token]={}
        return cache[token]
    points=[]
    for name in (a,b):
        items=query("geocode/geo",{"city":"武汉","address":name}).get("geocodes",[])
        items=[p for p in items if str(p.get("adcode","")).startswith("4201") and p.get("location") and p.get("level") not in ("市","区县","省")]
        if len(items)!=1:return []
        points.append(items[0]["location"])
    data=query("direction/transit/integrated",{"origin":points[0],"destination":points[1],"city":"武汉",
        "date":date,"time":f"{minute//60:02d}:{minute%60:02d}","extensions":"all"})
    options=[]
    for route in data.get("route",{}).get("transits",[]):
        try:
            segments=route["segments"]
            if any(any((s.get("railway") or {}).values()) or s.get("taxi") for s in segments):continue
            lines=[s["bus"]["buslines"][0] for s in segments if s.get("bus",{}).get("buslines")]
            if not lines:continue
            options.append(dict(mode="metro" if all("地铁" in l["type"] for l in lines) else "transit",
                minutes=ceil(float(route["duration"])/60),walk_m=int(route["walking_distance"]),changes=len(lines)-1,
                directions=" → ".join(l["departure_stop"]["name"]+"乘"+l["name"]+"至"+l["arrival_stop"]["name"] for l in lines),
                ticket=float(route["cost"]) if route.get("cost") else None,source="高德公交规划 "+date,
                departure_query=f"{minute//60:02d}:{minute%60:02d}",coordinates_gcj02=points,
                fare_bound=None))
        except (TypeError,ValueError,KeyError,IndexError):continue
    return options

def straight_km(a,b):
    p,q=ATLAS_POINTS.get(a),ATLAS_POINTS.get(b)
    if not p or not q:return None
    x=(q["lon"]-p["lon"])*cos(radians((p["lat"]+q["lat"])/2))
    return 111.2*hypot(x,q["lat"]-p["lat"])

def choose(a,b,mobility,minute,cache,strict=False):
    v=settings(mobility)
    people=v.get("人数")
    allowed=set(v.get("交通方式","walk,metro,transit,taxi").split(","))
    if "transit" in allowed:allowed.add("metro")
    cap=v.get("单段步行上限米")
    budget=min((v[k] for k in ("每日全团交通预算元","全程全团交通预算元") if k in v),default=None)
    pref=v.get("交通偏好",mobility.get("default_preference","fastest"))
    rows=[]
    if a==b:
        return dict(origin=a,destination=b,mode="walk",minutes=0,walk_m=0,changes=0,group_fare=0,fare_bound=0,source="同一集合点")
    obs=road(a,b)
    if "walk" in obs:
        metres,mins,snap=obs["walk"]
        rows.append(dict(mode="walk",minutes=max(1,mins+ceil(snap/65)),walk_m=metres+snap,changes=0,
                         group_fare=0,fare_bound=0,source="OSRM 步行路网，地图参考点",directions="沿步行路网前往"))
    else:
        km=straight_km(a,b)
        same_block=PLACES.get(a,{}).get("zone") is not None and PLACES.get(a,{}).get("zone")==PLACES.get(b,{}).get("zone")
        if km is not None and km<=1.5 and same_block:
            # Neighbouring stops in one historic block: budget a winding walk from map reference points.
            metres=round(km*1350)
            rows.append(dict(mode="walk",minutes=max(3,ceil(metres/65)),walk_m=metres,changes=0,group_fare=0,fare_bound=0,
                             source="地图参考点直线距离×1.35 估算",directions="相邻街区步行，按距离估算",estimated=True))
    if "taxi" in obs:
        metres,mins,_=obs["taxi"]
        km=metres/1000
        unit=round(10+1.8*max(0,min(km,10)-3)+2.7*max(0,km-10),2)
        cars=ceil(people/4) if people else None
        fixed=v.get("每车每段固定报价元")
        unit=unit if fixed is None else fixed
        rows.append(dict(mode="taxi",minutes=mins+10,walk_m=None,changes=0,cars=cars,capacity=4,
                         group_fare=round(cars*unit,2) if cars else None,unit_fare=unit,
                         fare_bound=cars*unit if fixed is not None and cars else None,road_m=metres,
                         directions="普通四乘客座出租车，含10分钟上车等候预算",source="游客固定报价" if fixed is not None else FARES))
    public=live_transit(a,b,v.get("出行日期"),minute,cache) if allowed & {"metro","transit"} else []
    for row in public:
        row["group_fare"]=people*row["ticket"] if people and row["ticket"] is not None else None
    if not public:
        start,end=ACCESS.get(a),ACCESS.get(b)
        path=metro_route(start,end)
        if path and 420<=minute and minute+path[0]+36<=1260:
            cost,hops=path
            public=[dict(mode="metro",minutes=cost+36,walk_m=None,changes=len(hops)-1,group_fare=None,fare_bound=None,
                   directions=" → ".join(f"{s}乘{line}" for s,line in hops)+" → "+end+"下车",
                   source="手册200–203页＋高德武汉线路图；两端接驳和等候共预留36分钟，班次待核")]
    rows.extend(public)
    feasible=[]
    for row in rows:
        if row["mode"] not in allowed:continue
        # A straight-line estimate is not a walkable path, so it cannot prove a hard walking cap.
        if cap is not None and (row["walk_m"] is None or row["walk_m"]>cap or row.get("estimated")):continue
        if budget is not None and (row["fare_bound"] is None or row["fare_bound"]>budget):continue
        feasible.append(row)
    if not feasible:
        if cap is not None or "交通方式" in v or budget is not None:
            details=[]
            if cap is not None:details.append(f"单段步行≤{cap}米")
            if budget is not None:details.append(f"全团交通预算{budget}元；计价器估价不能保证上限")
            if "交通方式" in v:details.append("限定"+"/".join(LABEL[x] for x in sorted(allowed)))
            raise ValueError(f"{a}到{b}缺少满足{'、'.join(details)}的可核实方案")
        return dict(origin=a,destination=b,minutes=transit(a,b),mode="estimate",changes=None,walk_m=None,
                    group_fare=None,fare_bound=None,source=("按两地距离粗估，实际交通待核" if PLACES[a].get("directory") or PLACES[b].get("directory") else "路网资料不足，按片区预留"))
    def rank(row):
        inf=float("inf")
        if budget is not None: return (row["fare_bound"],row["minutes"])
        if pref=="less_walk":return (row["walk_m"] if row["walk_m"] is not None else inf,row["minutes"])
        if pref=="cheap":return (row["group_fare"] if row["group_fare"] is not None else inf,row["minutes"])
        if pref=="fewer_changes":return (row["changes"],row["minutes"])
        if pref in ("metro","walk","taxi"):
            if pref=="metro" and row["mode"]=="walk" and (row["walk_m"]<=800 or (row["minutes"]<=20 and not strict)):
                return (False,row["minutes"])
            return (row["mode"]!=pref,row["minutes"])
        # Visitors walk short hops instead of waiting for a taxi or changing metro lines.
        if strict:return (row["minutes"],)
        return (not(row["mode"]=="walk" and row["minutes"]<=20),row["minutes"])
    best=min(feasible,key=rank)
    result=dict(origin=a,destination=b,**best)
    if best["mode"] in ("walk","taxi") and best["source"]!="地图参考点直线距离×1.35 估算":
        data=snapshot("road_network.json")
        layer=data["profiles"][best["mode"]]
        if "routed_points" in layer:
            result["routing_anchors"]={n:{"lonlat":layer["routed_points"][data["order"].index(n)],
                "crs":"WGS84","map_object":data["anchors"][n]["source"]} for n in (a,b)}
        result["checked"]=data["checked"]
    return result

