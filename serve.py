"""Local web and JSON entry point for the city receptionist."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import gzip
import hashlib
import hmac
import os
import re
from threading import BoundedSemaphore, Lock
from time import monotonic
from functools import lru_cache
from uuid import uuid4
from places import city_places
from route_edits import edit_route, editable_places
from limits import CapacityError, TurnExpired, turn_budget
from model import ModelError, deepseek_key
from urllib.parse import urlsplit
import requests
from agent import Agent
from knowledge import DATA, Knowledge, TOOLS, grounded
from copy import copy
from storage import Conflict
from diagnostics import capture,timed
from transport import snapshot

WEB_DIR = Path(__file__).resolve().parent / "web"
WEB_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/routes": ("routes.html", "text/html; charset=utf-8"),
    "/web/style.css": ("style.css", "text/css; charset=utf-8"),
    "/web/routes.css": ("routes.css", "text/css; charset=utf-8"),
    "/web/routes.js": ("dist/routes.js", "text/javascript; charset=utf-8"),
    "/web/route-time.js": ("dist/route-time.js", "text/javascript; charset=utf-8"),
    "/web/vendor/leaflet.css": ("vendor/leaflet.css", "text/css; charset=utf-8"),
    "/web/vendor/leaflet.js": ("vendor/leaflet.js", "text/javascript; charset=utf-8"),
    "/web/chat.js": ("dist/chat.js", "text/javascript; charset=utf-8"),
    "/web/avatar.js": ("dist/avatar.js", "text/javascript; charset=utf-8"),
    "/web/porpoise.webp": ("porpoise.webp","image/webp"),
    "/web/porpoise-face.webp": ("porpoise-face.webp","image/webp"),
    "/web/poster.js": ("dist/poster.js", "text/javascript; charset=utf-8"),
    "/web/wuhan-switchboard.webp": ("wuhan-switchboard.webp", "image/webp"),
    "/web/receptionist.webp": ("receptionist.webp","image/webp"),
    "/web/icon.png": ("icon.png","image/png"),
    "/web/hero-small.webp": ("hero-small.webp","image/webp"),
    "/web/compat.js": ("compat.js","text/javascript; charset=utf-8"),
    "/web/wuhan-schematic.png": ("wuhan-schematic.png","image/png"),
}


WEB_ASSETS.update({
    "/city": ("city.html", "text/html; charset=utf-8"),
    "/web/wuhan-map.js": ("dist/wuhan-map.js","text/javascript; charset=utf-8"),
    "/web/island/tiles.json": ("island/tiles.json","application/json"),
    "/web/city.js": ("dist/city.js", "text/javascript; charset=utf-8"),
    "/web/city.css": ("city.css", "text/css; charset=utf-8"),
})
for photo in (WEB_DIR / "atlas").glob("*.webp"):
    WEB_ASSETS["/web/atlas/"+photo.name] = ("atlas/"+photo.name, "image/webp")


for tile in (WEB_DIR / "island").glob("*.svg"):
    WEB_ASSETS["/web/island/"+tile.name] = ("island/"+tile.name,"image/svg+xml")


@lru_cache(maxsize=100)
def static_file(filename, media, mtime, compressed, header_mtime=0):
    data = (WEB_DIR / filename).read_bytes()
    if header_mtime:
        data = data.replace(b"<!-- shared-header -->", (WEB_DIR / "header.html").read_bytes())
    if compressed:
        data = gzip.compress(data, mtime=0)
    return data, '"' + hashlib.sha256(data).hexdigest() + '"'


class ReviewedSources:
    """Each turn keeps one consistent version, even if the source changes mid-turn."""
    def __init__(self, agent, path):
        self.agent = agent
        self.path = path
        self.lock = Lock()

    def current(self):
        with self.lock:
            try:
                rows = json.loads(self.path.read_bytes())
                if rows != self.agent.kb.curated:
                    revised = copy(self.agent)
                    revised.kb = Knowledge(curated=rows)
                    self.agent = revised
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise ModelError("资料更新待核验") from exc
            return self.agent


def handler(agent, hosts=None, invite="", session_cap=60, day_cap=300):
    hosts = {h.lower() for h in hosts} if hosts else None
    sources = ReviewedSources(agent, DATA/"official.json") if isinstance(agent.kb, Knowledge) else None
    session_locks = {}
    locks_guard = Lock()
    def session_lock(key):
        # One lock per session, so unrelated sessions never block each other.
        with locks_guard:
            if len(session_locks)>4096:
                for k in [k for k,l in session_locks.items() if not l.locked()]:del session_locks[k]
            return session_locks.setdefault(key,Lock())
    probe_lock = Lock()
    probe = {"next":0, "ok":False}

    def model_ready():
        with probe_lock:
            if monotonic() >= probe["next"]:
                m = agent.model
                try:
                    key = deepseek_key() if m.deepseek else os.getenv("SAIG_MODEL_KEY")
                    with requests.Session() as client:
                        client.trust_env = not m.deepseek or os.getenv("SAIG_DEEPSEEK_USE_PROXY")=="1"
                        r = client.get(m.base+"/models", headers={"Authorization":"Bearer "+key} if key else {},
                                       allow_redirects=False, timeout=(2,3))
                        probe["ok"] = r.ok and any(row.get("id")==m.name for row in r.json().get("data",[]))
                except (requests.RequestException, ModelError, ValueError, OSError):
                    probe["ok"] = False
                probe["next"] = monotonic() + (60 if probe["ok"] else 10)
            return probe["ok"]

    class API(BaseHTTPRequestHandler):
        timeout = 12

        def send_json(self,status,obj):
            data=json.dumps(obj,ensure_ascii=False).encode("utf8")
            self.send_response(status)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def allowed(self, write=False):
            host = self.headers.get("Host","").lower()
            allowed_hosts = hosts or {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if len(self.headers.get_all("Host",[])) != 1 or host not in allowed_hosts:
                self.send_json(403, {"error":"访问地址未获准"})
                return False
            origin = self.headers.get("Origin")
            if write and ((origin is not None and origin.lower() not in ("http://"+host,"https://"+host))
                          or self.headers.get("Sec-Fetch-Site")=="cross-site"):
                self.send_json(403, {"error":"仅接受本站请求"})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            path=urlsplit(self.path).path
            if path in WEB_ASSETS:
                filename,media=WEB_ASSETS[path]
                compressed=("gzip" in self.headers.get("Accept-Encoding","").lower().split(", ") and (media.startswith("text/") or media=="image/svg+xml"))
                file = WEB_DIR / filename
                if not file.is_file():
                    return self.send_json(404,{"error":"资源不存在"})
                data,etag=static_file(filename,media,file.stat().st_mtime_ns,compressed,
                                      (WEB_DIR/"header.html").stat().st_mtime_ns if media.startswith("text/html") else 0)
                unchanged=etag in self.headers.get("If-None-Match","").split(", ")
                self.send_response(304 if unchanged else 200)
                self.send_header("ETag",etag)
                self.send_header("Cache-Control","no-cache" if media.startswith("text/") else "public, max-age=300, must-revalidate")
                self.send_header("Vary","Accept-Encoding")
                self.send_header("Referrer-Policy","no-referrer")
                self.send_header("X-Content-Type-Options","nosniff")
                if not unchanged:
                    self.send_header("Content-Type",media)
                    self.send_header("Content-Length",str(len(data)))
                    if compressed:self.send_header("Content-Encoding","gzip")
                self.end_headers()
                if not unchanged:self.wfile.write(data)
            elif path=="/health":
                ok=model_ready()
                self.send_json(200 if ok else 503,{"status":"ok" if ok else "unavailable","model":agent.model.name,
                    "probe":"model_catalog","chunks":len(agent.kb.rows),"tools":[*TOOLS,"location"]})
            elif path=="/city-places":
                self.send_json(200,city_places())
            elif path=="/route-places":
                self.send_json(200,editable_places())
            elif path=="/showcase":
                self.send_json(200,snapshot("showcase.json"))
            elif path=="/route-points":
                self.send_json(200,{**snapshot("points.json"),**snapshot("road_network.json").get("anchors",{}),**snapshot("route_points.json")})
            else:
                self.send_json(404,{"error":"未知入口"})

        def do_POST(self):
            if not self.allowed(True):return
            if self.path not in ("/chat","/route-edit","/session/delete","/tool","/rag") or (invite and self.path in ("/tool","/rag")):
                return self.send_json(404,{"error":"未知入口"})
            if self.headers.get_content_type()!="application/json":
                return self.send_json(415,{"error":"需要 application/json"})
            if invite and not hmac.compare_digest(self.headers.get("X-SAIG-Invite","").encode(),invite.encode()):
                return self.send_json(401,{"error":"请从完整的试用邀请链接进入接待台。"})
            try:
                size=int(self.headers.get("Content-Length","0"))
                if not 0<size<=32768:return self.send_json(413,{"error":"请求大小无效"})
                body=json.loads(self.rfile.read(size))
                if not isinstance(body,dict):raise ValueError()
                sid=body.get("session") or uuid4().hex
                req=body.get("request_id") or uuid4().hex
                if any(not isinstance(x,str) or not 0<len(x)<=128 for x in (sid,req)):raise ValueError()
                if invite and not re.fullmatch(r"[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}",sid):raise ValueError()
                if self.path in ("/session/delete","/route-edit") and not body.get("session"):raise ValueError()
                if self.path=="/route-edit" and (not isinstance(body.get("change"),dict) or not body.get("request_id")):raise ValueError()
                q=body.get("query")
                if self.path not in ("/session/delete","/route-edit") and (not isinstance(q,str) or not 0<len(q.strip())<=3000):raise ValueError()
                if self.path in ("/tool","/rag") and body.get("tool") not in (*TOOLS,"location"):raise ValueError()
                if self.path=="/rag" and body["tool"]=="location":raise ValueError()
            except (ValueError,TypeError,UnicodeError):
                return self.send_json(400,{"error":"请求字段或格式无效"})
            internal=("invite:"+hashlib.sha256(sid.encode()).hexdigest()) if invite else sid
            lock=session_lock(internal)
            if not lock.acquire(blocking=False):
                return self.send_json(409,{"error":"会话正在处理，请稍后再试。"})
            attempts=0
            def charge():
                nonlocal attempts
                if attempts>=32:raise CapacityError("本轮达到模型调用上限，请拆分问题。")
                # Daily caps count visitor turns, not the model calls inside one turn.
                if not attempts:agent.store.charge(internal,session_cap,day_cap)
                attempts+=1
            try:
                current = sources.current() if sources and self.path!="/session/delete" else agent
                with turn_budget(charge):
                    if self.path=="/session/delete":
                        agent.store.delete(internal)
                        result={"deleted":True}
                    elif self.path=="/route-edit":
                        try:
                            result=edit_route(agent.store,internal,req,body["change"])
                        except Conflict:
                            raise
                        except ValueError as exc:
                            return self.send_json(422,{"error":str(exc)})
                    elif self.path=="/chat":
                        debug=not invite and body.get("diagnostics") is True
                        with capture(debug) as events,timed("chat"):
                            result={**current.respond(internal,q,req),"session":sid,"request_id":req}
                        if debug:result["events"]=events
                        if invite:
                            result.pop("trace",None)
                            result.pop("facts",None)
                    else:
                        rows=current.tool(body["tool"],q)
                        result=rows if self.path=="/tool" else grounded(agent.model,q,rows)
                self.send_json(200,result)
            except CapacityError as exc:self.send_json(429,{"error":str(exc)})
            except Conflict as exc:self.send_json(409,{"error":str(exc)})
            except TurnExpired as exc:self.send_json(504,{"error":str(exc)})
            except (requests.RequestException,ModelError):
                self.send_json(503,{"error":"模型或外部服务暂不可用，请稍后重试。"})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self.log_error("internal error %s",type(exc).__name__)
                self.send_json(500,{"error":"接待服务发生内部错误，请稍后重试。"})
            finally:
                lock.release()
    return API


class Server(ThreadingHTTPServer):
    def __init__(self,address,api,store):
        self.slots=BoundedSemaphore(12)
        self.store=store
        self.next_purge=monotonic()+60
        super().__init__(address,api)

    def service_actions(self):
        if monotonic()>=self.next_purge:
            self.store.purge()
            self.next_purge=monotonic()+60

    def process_request(self,request,address):
        if self.slots.acquire(blocking=False):
            return super().process_request(request,address)
        try:
            request.settimeout(1)
            request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nRetry-After: 3\r\nContent-Length: 0\r\n\r\n")
        finally:
            self.shutdown_request(request)

    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--port",type=int,default=18943)
    p.add_argument("--host",default="127.0.0.1")
    p.add_argument("--allowed-host",action="append",default=[])
    p.add_argument("--db",default=str(Path(__file__).parent/"sessions.sqlite"))
    args=p.parse_args()
    invite=os.getenv("SAIG_INVITE","")
    hosts=set(args.allowed_host)
    hosts.update(x.strip() for x in os.getenv("SAIG_ALLOWED_HOSTS","").split(",") if x.strip())
    if args.host!="127.0.0.1" or hosts or invite:
        if len(invite)<24 or not hosts:p.error("对外监听需要明确 --allowed-host 和至少 24 字符的 SAIG_INVITE")
    else:hosts={f"localhost:{args.port}",f"127.0.0.1:{args.port}"}
    agent=Agent(args.db)
    api=handler(agent,hosts,invite,int(os.getenv("SAIG_SESSION_CAP","60")),int(os.getenv("SAIG_DAY_CAP","300")))
    Server((args.host,args.port),api,agent.store).serve_forever()
