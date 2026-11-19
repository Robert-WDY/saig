import json
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from knowledge import _verify_statement
from limits import CapacityError, charge_attempt, turn_budget
from model import Model, ModelError
from semantics import compile_day
from serve import handler
from storage import Sessions
from visitor_turn import interpret_turn


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "db")
        self.store = Sessions(self.path)

    def test_legacy_migration_expiry_and_removal_of_answers(self):
        legacy = str(Path(self.tmp.name) / "legacy")
        with closing(sqlite3.connect(legacy)) as db, db:
            db.execute("CREATE TABLE session(id TEXT PRIMARY KEY,rev INTEGER,state TEXT)")
            db.execute("INSERT INTO session VALUES('old',1,'{}')")
        store = Sessions(legacy)
        store.save("old", "req", "q", 1, {}, {"answer":"a"})
        store.save("fresh", "req", "q", 0, {}, {})
        with closing(sqlite3.connect(legacy)) as db, db:
            db.execute("UPDATE session SET touched=1 WHERE id='old'")
        store.purge()
        self.assertEqual(store.read("old","req","q")[::2], (0,None))
        self.assertIsNotNone(store.read("fresh","req","q")[2])

    def test_daily_budget_atomic_across_sessions_and_restarts(self):
        def call(n):
            try:
                self.store.charge(str(n), 8, 4)
                return True
            except CapacityError:
                return False
        with ThreadPoolExecutor(8) as pool:
            self.assertEqual(sum(pool.map(call, range(10))), 4)
        with self.assertRaises(CapacityError):
            Sessions(self.path).charge("another",8,4)

    def test_upstream_retry_charges_attempts(self):
        model=Model(base="http://127.0.0.1:1")
        session=Mock()
        model._http.session=session
        busy=Mock(status_code=429,headers={"Retry-After":"0"})
        ok=Mock(status_code=200)
        ok.json.return_value={"choices":[{"message":{"content":"{}"}}]}
        session.post.side_effect=[busy,ok]
        charge=Mock()
        with turn_budget(charge):
            self.assertEqual(model.ask("q",{}),{})
        self.assertEqual(charge.call_count,2)
        session.post.side_effect=requests.ReadTimeout()
        with self.assertRaises(requests.ReadTimeout):
            model.ask("q",{})
        self.assertEqual(session.post.call_count,3)

    def test_contract_and_citation_checks_without_network(self):
        model=Mock()
        model.ask.return_value={"mode":"compose","outputs":["单日","两日"],"facts":[]}
        self.assertEqual(interpret_turn(model,"比较两套",{"turns":[],"days":{},"facts":[]},Mock()),{"mode":"compose"})
        with self.assertRaises(ValueError):
            compile_day({"query":"调整","changes":[{"field":"start","quote":"九点","value":"540"}]},1,"保持原样")
        model.ask.return_value={"待证关系":"地址","编号":"a","逐字证据":"另一处"}
        result=_verify_statement(model,"地址","地点在哪",[{"id":"a","text":"这个场馆位于智民里"}])
        self.assertFalse(result["supported"])

    def test_public_http_boundary_errors_and_delete(self):
        agent=Mock()
        agent.store=self.store
        agent.kb.rows=[]
        agent.model.name="test"
        base_handler=handler(agent,{"test.local"},"a"*24,1,4)
        base_handler.log_message=lambda *args:None
        server=ThreadingHTTPServer(("127.0.0.1",0),base_handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base=f"http://127.0.0.1:{server.server_port}"
        request={"session":"1"*32,"query":"q"}
        headers={"Host":"test.local","X-SAIG-Invite":"a"*24,"Origin":"https://test.local"}
        http=requests.Session()
        http.trust_env=False
        self.addCleanup(http.close)
        def send(**kw):
            return http.post(base+"/chat",timeout=2,**kw)
        self.assertEqual(send(json=request,headers={**headers,"Host":"wrong.test"}).status_code,403)
        self.assertEqual(send(json=request,headers={**headers,"Origin":"https://other.test"}).status_code,403)
        self.assertEqual(send(json=request,headers={"Host":"test.local"}).status_code,401)
        self.assertEqual(send(data="{}",headers={**headers,"Content-Type":"text/plain"}).status_code,415)
        self.assertEqual(send(json={},headers=headers).status_code,400)
        self.assertEqual(http.post(base+"/tool",json=request,headers=headers).status_code,404)
        agent.respond.assert_not_called()
        def respond(sid,q,req):
            charge_attempt()
            return self.store.save(sid,req,q,0,{},{"answer":"ok"})
        agent.respond.side_effect=respond
        self.assertEqual(send(json=request,headers=headers).status_code,200)
        self.assertEqual(send(json=request,headers=headers).status_code,429)
        self.assertEqual(http.post(base+"/session/delete",json=request,headers=headers).status_code,200)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM response").fetchone()[0],0)
        agent.respond.side_effect=KeyError()
        self.assertEqual(send(json=request,headers=headers).status_code,500)
        agent.respond.side_effect=ModelError()
        self.assertEqual(send(json=request,headers=headers).status_code,503)
        with patch("serve.deepseek_key",side_effect=ModelError()):
            self.assertEqual(http.get(base+"/health",headers=headers).status_code,503)
        css=http.get(base+"/web/style.css",headers=headers)
        self.assertEqual(css.headers["Content-Encoding"],"gzip")
        self.assertEqual(http.get(base+"/web/style.css",headers={**headers,"If-None-Match":css.headers["ETag"]}).status_code,304)
