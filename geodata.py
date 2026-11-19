"""Refresh point references from MediaWiki's public coordinates API; omit unresolved titles."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import requests
from places import PLACES

def main():
    aliases={"江汉关":"江汉关大楼"}
    titles={aliases.get(n,n):n for n in PLACES}
    r=requests.get("https://zh.wikipedia.org/w/api.php",params={"action":"query","format":"json",
        "prop":"coordinates|info","inprop":"url","titles":"|".join(titles)},timeout=20,
        headers={"User-Agent":"SAIG-WuhanGuide/0.1 (educational point of interest catalog)"})
    r.raise_for_status()
    points={}
    for p in r.json()["query"]["pages"].values():
        coords=p.get("coordinates",[])
        if coords and p["title"] in titles:
            point=coords[0]
            if 29<point["lat"]<32 and 113<point["lon"]<116:
                points[titles[p["title"]]]={"lat":point["lat"],"lon":point["lon"],"crs":"WGS84",
                    "source":p["fullurl"],"usage":"地标参考点，入口以地图与现场为准"}
    if not points:
        raise ValueError("未取得坐标，保留已有数据")
    dest=Path(__file__).parent/"data"/"points.json"
    with NamedTemporaryFile("w",encoding="utf8",dir=dest.parent,delete=False) as out:
        json.dump(points,out,ensure_ascii=False,indent=2)
    os.replace(out.name,dest)
    print(len(points))

if __name__=="__main__":
    main()
