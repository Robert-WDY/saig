"""Run sealed query-only conversations through the HTTP app; judges and criteria stay out of payloads."""
import argparse,hashlib,json,sys,tempfile,time
from pathlib import Path
from threading import Thread
from http.server import ThreadingHTTPServer
import requests
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agent import Agent
from serve import handler

def capture(spec,out):
    cases=json.loads(spec.read_text(encoding="utf8"))
    if out.exists():raise FileExistsError(out)
    result={"spec_sha256":hashlib.sha256(spec.read_bytes()).hexdigest(),"turns":[]}
    with tempfile.TemporaryDirectory() as tmp, requests.Session() as client:
        client.trust_env=False
        agent=Agent(str(Path(tmp)/"sessions.sqlite"))
        server=ThreadingHTTPServer(("127.0.0.1",0),handler(agent))
        Thread(target=server.serve_forever,daemon=True).start()
        try:
            for i,(sid,query,_) in enumerate(cases,1):
                before=agent.store.read(sid,"inspect","inspect")[1]
                start=time.monotonic()
                reply=client.post(f"http://127.0.0.1:{server.server_port}/chat",
                    json={"session":sid,"request_id":str(i),"query":query},timeout=300)
                reply.raise_for_status()
                after=agent.store.read(sid,"inspect","inspect")[1]
                result["turns"].append({"session":sid,"input":query,"response":reply.json(),"before":before,
                    "after":after,"seconds":round(time.monotonic()-start,2)})
                out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
        finally:
            server.shutdown()
            server.server_close()

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("spec",type=Path);p.add_argument("out",type=Path)
    a=p.parse_args();capture(a.spec,a.out)
