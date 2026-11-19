"""Named POIs and conservative planning allowances. Map links resolve by city and name."""
from urllib.parse import urlencode
import os
import json
from pathlib import Path
import requests

# name, anchor/area, planning cluster, suggested visit minutes, archive/official source ID
ROWS = [
    ("江汉路","汉口，江汉关至京汉大道一带","汉口老城",40,"towns"),
    ("智民里","江岸历史街区，江汉路站、大智路站附近","汉口老城",40,"venue"),
    ("黎黄陂路","江岸区历史风貌街区","汉口老城",35,"oldtown"),
    ("江汉关","江汉路南端、沿江大道一带","汉口老城",25,"towns"),
    ("吉庆街","汉口大智路附近美食街区","汉口老城",40,"book.165.1"),
    ("汉口江滩","汉口沿江公共空间，具体入口需选定","汉口江岸",50,"book.201.1"),
    ("山海关路","江岸区老街美食街区","汉口江岸",35,"book.167.1"),
    ("汉口站","汉口火车站","汉口车站",0,"book.205.1"),
    ("昙华林","武昌古城历史文化街区","武昌古城",45,"book.200.1"),
    ("户部巷","武昌老城美食街区","武昌古城",35,"book.164.1"),
    ("粮道街","武昌区粮道街","武昌古城",40,"book.165.1"),
    ("黄鹤楼","武昌蛇山；默认周边观景，入园另核时间","武昌古城",60,"book.6.1"),
    ("湖北省博物馆","武昌区东湖路160号；入馆需核实预约","东湖",90,"book.16.1"),
    ("东湖绿道","东湖风景区，需确定具体入口","东湖",60,"book.8.1"),
    ("武汉大学","武昌珞珈山，校内参观需核实","武昌珞珈",60,"book.175.1"),
]
PLACES = {n:dict(name=n, area=a, zone=z, minutes=m, evidence=s) for n,a,z,m,s in ROWS}
for name, zone, minutes, source in json.loads((Path(__file__).parent/"data/guide_places.json").read_text("utf8")):
    PLACES[name] = dict(name=name, area=zone, zone=zone, minutes=minutes, evidence=source)


def region(name):
    zone = PLACES[name]["zone"]
    return next((prefix for prefix in ("汉阳", "汉口") if zone.startswith(prefix)), "武昌")


def amap_key():
    for name in ("SAIG_AMAP_KEY","AMAP_KEY","GAODE_API_KEY"):
        value=os.getenv(name)
        if value:return value
    if os.name=="nt":
        import win32cred
        try:
            credential=win32cred.CredRead("SAIG/AMap",win32cred.CRED_TYPE_GENERIC)
        except win32cred.error as exc:
            if exc.winerror!=1168:raise
        else:
            return credential["CredentialBlob"].decode("utf-16-le")
    return None

def locate(query):
    matches = [dict(p, map_url="https://uri.amap.com/search?"+urlencode({"keyword":p["name"],"city":"武汉"}))
               for p in PLACES.values() if query in p["name"] or p["name"] in query]
    data=Path(__file__).parent/"data"/"points.json"
    points=json.loads(data.read_text(encoding="utf8")) if data.exists() else {}
    for p in matches:
        p["point"]=points.get(p["name"])
    # Optional live geocoding. Without it the tool returns sourced locations and map handoffs.
    if key := amap_key():
        try:
            r = requests.get("https://restapi.amap.com/v3/geocode/geo",
                             params={"key":key,"address":query,"city":"武汉"},timeout=8)
            r.raise_for_status()
            payload = r.json()
        except (requests.RequestException,ValueError):
            return {"catalog":matches,"geocodes":[],"notice":"外部地址查询暂不可用，仅返回本地目录结果。"}
        if payload.get("status") == "1":
            candidates=[p for p in payload.get("geocodes",[])
                        if p.get("adcode","").startswith("4201") and p.get("location")
                        and p.get("level") not in ("省","市","区县","未知")
                        and query.strip() and query.strip() in p.get("formatted_address","")]
            if len(candidates)==1:
                p=candidates[0]
                return {"catalog":matches,"geocodes":[{"address":p["formatted_address"],"gcj02":p["location"],"level":p["level"]}]}
    return {"catalog":matches,"geocodes":[]}


def transit(a,b):
    if a==b:
        return 0
    x,y = PLACES[a]["zone"], PLACES[b]["zone"]
    if x==y:
        return 25
    if region(a) != region(b):
        return 100
    if x.startswith("汉口") and y.startswith("汉口"):
        return 60 if "汉口车站" in (x,y) else 40
    if x.startswith("汉口") != y.startswith("汉口"):
        return 100
    return 65
