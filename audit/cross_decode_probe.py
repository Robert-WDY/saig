"""Replay a frozen extraction request across prompt-cache contexts, holding the schema and sampling fixed."""
import hashlib,json,sys
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from feedback import FRAME
from model import Model
from unittest.mock import patch
def run(out):
    trial=json.loads((ROOT/'audit/benchmark-1118-new/repeat.json').read_text(encoding='utf8'))[0]
    call=next(c for c in trial['calls'] if '操作' in c['result'])
    original=requests.post
    rows=[]
    for cache in (True,False):
        for variant in ('cold','prefix','long','prefix','cold','long'):
            def send(url,**kw):
                body=kw['json']
                body.update(cache_prompt=cache,seed=42)
                before=json.loads(json.dumps(body,ensure_ascii=False))
                before['messages'][1]['content']={'cold':'只返回空数组','long':body['messages'][1]['content']+' 之前的错误需要重新分析。','prefix':body['messages'][1]['content'][:-25]}[variant]
                before['max_tokens']=16
                original(url,**{**kw,'json':before}).raise_for_status()
                return original(url,**kw)
            with patch.object(requests,'post',send):
                result=Model().ask(call['instruction'],call['input'],900,FRAME)
            rows.append(dict(cache=cache,prior=variant,response=result))
            out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':run(Path(sys.argv[1]))
