"""Integration points outside chat: data refresh, optional provider, CLI and the public RAG endpoint."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import Mock,patch
import requests
import geodata
from places import locate

def run(out,base):
    rows=[]
    def case(name,expect,fn):
        try: good,observed=fn()
        except Exception as e: good,observed=False,repr(e)
        rows.append({"id":name,"expected":expect,"passed":bool(good),"observed":observed})
    def refresh():
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"data").mkdir()
            dest=root/"data"/"points.json"
            response=Mock()
            response.json.return_value={"query":{"pages":{"1":{"title":"江汉关大楼","fullurl":"fixture:building",
                "coordinates":[{"lat":30.56,"lon":114.29}]},"2":{"title":"汉口站","fullurl":"fixture:bad",
                "coordinates":[{"lat":114.24,"lon":30.62}]}}}}
            with patch.object(geodata,"__file__",str(root/"geodata.py")),patch.object(geodata.requests,"get",return_value=response):
                geodata.main()
                first=dest.read_bytes()
                data=json.loads(first)
                response.json.return_value={"query":{"pages":{}}}
                try: geodata.main()
                except ValueError: pass
                else: return False,"空快照覆盖了旧版本"
                return set(data)=={"江汉关"} and data["江汉关"]["crs"]=="WGS84" and dest.read_bytes()==first,data
    case("refresh_alias_and_atomicity","别名对齐、反转的经纬度拒收，无有效快照时保留前一版",refresh)
    def geocode():
        response=Mock()
        response.json.return_value={"status":"1","geocodes":[{"formatted_address":"武汉市测试点","adcode":"420102","location":"114.29,30.56","level":"门牌号"},
            {"formatted_address":"同名外市地点","adcode":"310102","location":"121.0,31.0","level":"门牌号"}]}
        with patch.dict(os.environ,{"SAIG_AMAP_KEY":"fixture"}),patch("places.requests.get",return_value=response):
            result=locate("测试点")
        return result=={"catalog":[],"geocodes":[{"address":"武汉市测试点","gcj02":"114.29,30.56","level":"门牌号"}]},result
    case("geocoder_jurisdiction","供应商返回外市同名点时只交付武汉地址并保留GCJ-02",geocode)
    def outage():
        with patch.dict(os.environ,{"SAIG_AMAP_KEY":"fixture"}),patch("places.requests.get",side_effect=requests.Timeout("injected")):
            try:
                result=locate("汉口站")
            except requests.Timeout:
                return False,"上游超时覆盖了本可返回的汉口站本地坐标"
        return any(p.get("point") for p in result.get("catalog",[])),result
    case("geocoder_degraded","远程超时仍应交付本地已知坐标，标明外部查询未完成",outage)
    def cli():
        cli=Path(__file__).parent/"app.py"
        result=subprocess.run([sys.executable,str(cli),"tool","黄鹤楼","--tool","attraction"],
                              capture_output=True,encoding="utf8",timeout=20,check=True)
        docs=json.loads(result.stdout)
        return docs[0]["id"]=="book.6.1" and docs[0]["category"]=="attraction",[r["id"] for r in docs]
    case("cli_to_catalog","从命令行查询景点，输出能解析并优先命中景点正文",cli)
    def api():
        r=requests.post(base+"/rag",json={"tool":"saig","query":"线上参赛演示视频可以不交吗？"},timeout=180)
        r.raise_for_status()
        body=r.json()
        return body["supported"] and any(c["id"]=="register" and "视频" in c["quote"] for c in body["citations"]) and "视频" in body["answer"],body
    case("public_rag","经公开RAG端点问选填与必填，核对输出、引用及原文",api)
    out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True,type=Path);p.add_argument("--base",default="http://127.0.0.1:18943")
    args=p.parse_args();run(args.out,args.base)
