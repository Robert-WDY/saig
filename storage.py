import json
import sqlite3
import time
from limits import CapacityError
from contextlib import closing


class Conflict(ValueError):
    pass


class Sessions:
    def __init__(self,path):
        self.path=path
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS session(id TEXT PRIMARY KEY, rev INTEGER NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS response(session TEXT, req TEXT, question TEXT, result TEXT,
                PRIMARY KEY(session,req));
            CREATE TABLE IF NOT EXISTS usage(day INTEGER NOT NULL, bucket TEXT NOT NULL, count INTEGER NOT NULL,
                PRIMARY KEY(day,bucket));
            """)
            db.execute("BEGIN IMMEDIATE")
            if "touched" not in {r[1] for r in db.execute("PRAGMA table_info(session)")}:
                db.execute("ALTER TABLE session ADD COLUMN touched INTEGER NOT NULL DEFAULT 0")
                db.execute("UPDATE session SET touched=?", (int(time.time()),))
            db.execute("CREATE INDEX IF NOT EXISTS session_touched ON session(touched)")
        self.purge()

    def purge(self):
        cutoff = int(time.time()) - 86400
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM response WHERE session IN (SELECT id FROM session WHERE touched<=?)", (cutoff,))
            db.execute("DELETE FROM session WHERE touched<=?", (cutoff,))
            db.execute("DELETE FROM usage WHERE day < ?", ((int(time.time())+28800)//86400,))

    def delete(self, sid):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM response WHERE session=?", (sid,))
            db.execute("DELETE FROM session WHERE id=?", (sid,))

    def charge(self, sid, per_session, daily):
        day = (int(time.time())+28800)//86400
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            for bucket, limit in (("total", daily), ("s:"+sid, per_session)):
                row = db.execute("SELECT count FROM usage WHERE day=? AND bucket=?", (day,bucket)).fetchone()
                if (row[0] if row else 0) >= limit:
                    raise CapacityError("今日模型请求额度已用完，北京时间零点更新。")
                db.execute("INSERT INTO usage VALUES(?,?,1) ON CONFLICT(day,bucket) DO UPDATE SET count=count+1",
                           (day,bucket))

    def read(self,sid,req,question):
        with closing(sqlite3.connect(self.path)) as db:
            cached=db.execute("SELECT question,result FROM response WHERE session=? AND req=?",(sid,req)).fetchone()
            if cached and cached[0]!=question:
                raise Conflict("相同请求编号对应不同输入")
            row=db.execute("SELECT rev,state FROM session WHERE id=?",(sid,)).fetchone()
        rev,state=(row[0],json.loads(row[1])) if row else (0,{"days":{},"facts":[],"turns":[]})
        return rev,state,json.loads(cached[1]) if cached else None

    def save(self,sid,req,q,rev,state,result):
        with closing(sqlite3.connect(self.path,timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            cached=db.execute("SELECT question,result FROM response WHERE session=? AND req=?",(sid,req)).fetchone()
            if cached:
                if cached[0]!=q:
                    raise Conflict("相同请求编号对应不同输入")
                return json.loads(cached[1])
            row=db.execute("SELECT rev FROM session WHERE id=?",(sid,)).fetchone()
            if (row[0] if row else 0)!=rev:
                raise Conflict("会话刚刚更新，请在最新行程上重试")
            db.execute("INSERT OR REPLACE INTO session(id,rev,state,touched) VALUES(?,?,?,?)",
                       (sid,rev+1,json.dumps(state,ensure_ascii=False),int(time.time())))
            db.execute("INSERT INTO response VALUES(?,?,?,?)",(sid,req,q,json.dumps(result,ensure_ascii=False)))
        return result
