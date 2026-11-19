"""Refresh named Wuhan map anchors and directed road-network estimates (OSM attribution in output)."""
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from places import PLACES

ROOT = Path(__file__).parent / "data"
OUTPUT = ROOT / "road_network.json"
CONTACT = {"User-Agent": "SAIG-Wuhan-city-receptionist/1.0 (Wuhan tourism itinerary research)"}
SEARCH = "https://nominatim.openstreetmap.org/search"
ROUTER = "https://routing.openstreetmap.de"
ALIASES = {"江汉关":"江汉关博物馆","黄鹤楼":"黄鹤楼","光谷空轨":"高新大道站","三镇民生甜食馆":"三镇民生甜食馆胜利街店","东湖听涛":"东湖听涛景区"}

def fetch(routes_only=False):
    existing = json.loads(OUTPUT.read_text("utf8")) if OUTPUT.exists() else {}
    anchors = existing.get("anchors", {})
    for name,anchor in list(anchors.items()):
        if name=="汉口江滩" and anchor["label"]!="汉口江滩":
            del anchors[name]
    points = json.loads((ROOT/"points.json").read_text("utf8"))
    for name in PLACES:
        if name in anchors or routes_only:
            continue
        query = ALIASES.get(name, name)
        try:
            response = requests.get(SEARCH, params={"q":query+" 武汉","format":"jsonv2","limit":4,
                "viewbox":"114.12,30.73,114.57,30.40","bounded":1,"accept-language":"zh-CN"}, headers=CONTACT,timeout=12)
            response.raise_for_status()
            matches = response.json()
            accepted={query,name,"斗级营街区" if name=="斗级营" else name,
                      "汉阳造广告创意园" if name=="汉阳造" else name,"万松园路" if name=="万松园" else name}
            hit = next((x for x in matches if x.get("name","") in accepted and
                        30.4 < float(x["lat"]) < 30.73 and 114.12 < float(x["lon"]) < 114.57),None)
            if hit:
                anchors[name] = {"label":hit["name"],"lat":float(hit["lat"]),"lon":float(hit["lon"]),
                                 "source":f"https://www.openstreetmap.org/{hit['osm_type']}/{hit['osm_id']}"}
        except (ValueError, requests.RequestException) as exc:
            print(name, type(exc).__name__,flush=True)
        if name not in anchors and name in points:
            anchors[name] = {k:points[name][k] for k in ("lat","lon","source")}
            anchors[name]["label"] = name
        time.sleep(1.1)
    names = list(anchors)
    coords = ";".join(f"{anchors[n]['lon']},{anchors[n]['lat']}" for n in names)
    out = {"attribution":"© OpenStreetMap contributors, ODbL 1.0; routing.openstreetmap.de / OSRM",
           "checked":datetime.now(timezone.utc).isoformat(),"anchors":anchors,"order":names,"profiles":{}}
    for mode, profile in (("walk","foot"),("taxi","car")):
        url = f"{ROUTER}/routed-{profile}/table/v1/driving/{coords}"
        r = requests.get(url,params={"annotations":"distance,duration"},headers=CONTACT,timeout=60)
        r.raise_for_status()
        data = r.json()
        if data.get("code")!="Ok" or len(data["distances"])!=len(names):
            raise ValueError("Invalid routing matrix")
        out["profiles"][mode] = {"seconds":data["durations"],"metres":data["distances"],
            "snap_metres":[math.ceil(a["distance"]) for a in data["sources"]],
            "routed_points":[a["location"] for a in data["sources"]],"source":r.url}
    staged = OUTPUT.with_suffix(".tmp")
    staged.write_text(json.dumps(out,ensure_ascii=False,separators=(",",":")),encoding="utf8")
    staged.replace(OUTPUT)
    print(len(names), "located out of",len(PLACES),flush=True)

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--routes-only",action="store_true")
    fetch(parser.parse_args().routes_only)

