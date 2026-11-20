"""Tools for the receptionist kernel.

Each tool has a JSON Schema that is checked before it runs; a bad call gets a precise error back
instead of an exception. Read tools never change the session; write tools (plan_trip, edit_trip,
remember) change exactly the session draft they were given. Trip times always come from the
deterministic scheduler (Agent.day), never from the model.
"""
import json
import re
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from knowledge import TOOLS as TOPICS
from places import PLACES, ATLAS
from planning import Invalid
from trip_contract import GUIDES, trip_review
from datetime import date as _date, timedelta as _td
from planning import HOURS, WEEKDAYS, WEEKDAY_CN, window_of, closed_on, evaluate, new_contract, reorder
from datetime import datetime as _dt, timezone as _tz
from itertools import combinations as _combos
from transport import ACCESS, metro_route, snapshot, straight_km
from weather import forecast

SKILL_DIR = Path(__file__).parent / "skills"
WRITE_TOOLS = {"plan_trip", "edit_trip", "remember", "multi_plan"}

# Everyday names visitors use for catalogue places.
ALIASES = {
    "光谷": "光谷广场", "武大": "武汉大学", "华科": "华中科技大学", "华中大": "华中科技大学", "华师": "华中师范大学",
    "省博": "湖北省博物馆", "省博物馆": "湖北省博物馆", "湖北博物馆": "湖北省博物馆", "东湖": "东湖听涛", "东湖绿道": "东湖绿道",
    "江滩": "汉口江滩", "长江大桥": "武汉长江大桥", "大桥": "武汉长江大桥", "汉街": "楚河汉街", "楚河": "楚河汉街",
    "吉庆街": "吉庆街", "黎黄陂": "黎黄陂路", "江汉关博物馆": "江汉关", "辛亥": "辛亥革命博物馆", "红楼": "辛亥革命博物馆",
    "汉口火车站": "汉口站", "汉口高铁站": "汉口站", "社区": "智民里", "数命社区": "智民里", "spu社区": "智民里", "会场": "智民里",
    "古琴台": "古琴台", "龟山": "龟山公园", "晴川阁": "晴川阁", "昙华林": "昙华林", "户部巷": "户部巷",
}


def _clock(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", value.strip()):
        raise Invalid(f"时间格式应为 HH:MM，收到 {value!r}")
    h, m = map(int, value.strip().split(":"))
    return h * 60 + m


def hhmm(t):
    return f"{t // 60:02d}:{t % 60:02d}"


def resolve(name):
    """Map a visitor's place name onto the plannable catalogue, or explain what is close."""
    raw = (name or "").strip()
    key = raw.lower().replace(" ", "")
    if raw in PLACES:
        return raw, []
    if key in ALIASES and ALIASES[key] in PLACES:
        return ALIASES[key], []
    hits = [n for n in PLACES if raw and (raw in n or n in raw)]
    if len(hits) == 1:
        return hits[0], []
    if not hits:
        hits = sorted(PLACES, key=lambda n: -len(set(n) & set(raw)))[:4] if raw else []
    return None, hits[:5]


def _metro(name):
    station = ACCESS.get(name)
    if not station:
        return None
    lines = [line for line, stops in snapshot("metro_lines.json")["lines"].items() if station in stops]
    return {"station": station + "站", "lines": lines}


FOOD = [r["name"] for r in ATLAS if r.get("category") == "美食" and r["name"] in PLACES and PLACES[r["name"]].get("minutes")]
LUNCH = [11 * 60, 13 * 60 + 45]


def opening_notes(days):
    """What the visitor should know about each stop's hours: booking, closed days, last entry."""
    out = []
    for key in sorted(days, key=int):
        card = days[key]
        when = card["contract"].get("date")
        for s in card["audit"]["stops"]:
            h = HOURS.get(s["place"])
            if not h or h.get("all_day"):
                continue
            bits = []
            if h.get("closed") and not when:
                bits.append("周" + "、周".join(WEEKDAY_CN[d] for d in h["closed"]) + "闭馆")
            if h.get("booking"):
                bits.append("需提前预约")
            if h.get("last_entry"):
                bits.append(h["last_entry"] + " " + h.get("entry_word", "停止入场"))
            if h.get("note"):
                bits.append(h["note"])
            if bits:
                out.append(f"第{key}天 {s['place']}：" + "，".join(bits) + f"（官方手册 {h['ref']}）")
    return out


def lunch_stop(card):
    for s in card["audit"]["stops"]:
        if s["place"] in FOOD and s["start"] < LUNCH[1] and s["end"] > LUNCH[0]:
            return s["place"]
    return None


# Windows bound when a stop is visited (start no earlier than, finish no later than), in minutes.
PERIODS = {"morning": [0, 12 * 60 + 30], "afternoon": [13 * 60, 23 * 60 + 59], "evening": [17 * 60, 23 * 60 + 59]}
GATEWAYS = {"天河机场": "天河机场", "汉口站": "汉口火车站", "武汉站": "武汉火车站", "武昌站": "武昌火车站"}
# Official community material: the 智民里 venue is by 江汉路站 (lines 2/6) and 大智路站 (lines 1/6).
VENUE_STATIONS = {"智民里": "江汉路", "数命SPU社区": "江汉路"}
METRO_STATIONS = {s for stops in snapshot("metro_lines.json")["lines"].values() for s in stops}


def idle_gaps(card, least=30):
    """Free time the scheduler left before a stop (e.g. waiting for a moved stop's window)."""
    stops, out = card["audit"]["stops"], []
    for prev, stop in zip(stops, stops[1:]):
        arrive = prev["end"] + (stop.get("leg") or 0)
        if stop["start"] - arrive >= least:
            out.append(f"{hhmm(arrive)}–{hhmm(stop['start'])} 到{stop['place']}之前空出约 {stop['start'] - arrive} 分钟")
    return out


def day_lines(days):
    out = []
    for key in sorted(days, key=int):
        card = days[key]
        stops = " → ".join(f"{hhmm(s['start'])} {s['place']}" for s in card["audit"]["stops"])
        c = card["contract"]
        tail = f"（约 {hhmm(card['audit']['arrival'])} 到{c['destination']}）" if c.get("destination") else ""
        out.append(f"第{key}天：{stops}{tail}")
    return out


SCHEMAS = {
    "search_knowledge": {
        "description": "检索官方资料（武汉旅游产品手册、武汉概览、数命SPU社区与SPU说明、SAIG赛事说明及核对过的官网要点）。回答任何关于武汉、景点美食、社区、SPU、SAIG 的事实前都要先检索，并在回答中用 [S编号] 引用。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["query"], "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 120, "description": "简短的检索词，2–12 个字，例如「热干面 哪里吃」「SAIG 报名 材料」"},
            "topic": {"type": "string", "enum": ["wuhan", "attraction", "food", "guide", "community", "spu", "saig", "any"],
                      "description": "资料范围：wuhan 城市概况/历史，attraction 景点，food 美食，guide 游玩攻略，community 数命SPU社区，spu SPU 概念，saig 赛事，any 全部"},
            "k": {"type": "integer", "minimum": 1, "maximum": 6}}}},
    "read_source": {
        "description": "读取某条检索结果的完整原文（检索结果只给摘录时使用）。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["ref"],
                       "properties": {"ref": {"type": "string", "pattern": "^S\\d+$"}}}},
    "find_place": {
        "description": "查地点：是否可排进行程、所在片区、建议停留时长、最近地铁站和导航链接。游客说的名字不标准时（如「光谷」「省博」）也用它找到目录里的正式名称。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["name"],
                       "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 40}}}},
    "get_weather": {
        "description": "查武汉实时天气和未来几天预报（天气、最高/最低气温、风、日出日落、空气质量）。排行程、问穿衣、问适合去哪玩、问看日落夜景时使用：下雨就优先室内（省博、美术馆、商场街区），日落时间决定江滩/长江大桥看夜景的时点。",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "days": {"type": "integer", "minimum": 1, "maximum": 7, "description": "要看几天，默认 3"}}}},
    "arrival_guide": {
        "description": "到达武汉的接站指引：从天河机场 / 汉口站 / 武汉站 / 武昌站坐地铁到目的地（会场智民里、酒店附近地标或景点）的线路、换乘和大致时间。来宾问「下了飞机/火车怎么去」时使用。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["gateway"], "properties": {
            "gateway": {"type": "string", "enum": ["天河机场", "汉口站", "武汉站", "武昌站"]},
            "destination": {"type": "string", "maxLength": 40, "description": "目的地，默认智民里（SAIG 线下赛会场）"}}}},
    "nearby": {
        "description": "查某个位置附近此刻（或指定时间）开着、可以去的地方，按距离排，含开放时间和是否需要预约。游客说「X 关门了/去不了，附近还有什么」「我在 X，附近有什么好玩/好吃的」时使用。不知道游客在哪就先问位置。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["location"], "properties": {
            "location": {"type": "string", "minLength": 1, "maxLength": 40, "description": "游客现在所在的地点、地铁站或地标"},
            "kind": {"type": "string", "enum": ["any", "sight", "food", "indoor"], "description": "想找什么：景点 / 吃的 / 室内（下雨时）"},
            "exclude": {"type": "array", "maxItems": 8, "items": {"type": "string"}, "description": "排除的地点（如刚关门的那个）"}}}},
    "plan_now": {
        "description": "临时安排：从游客现在的位置出发，按此刻时间和当天的开放时间，排接下来几个小时（如「接下来 3 小时怎么玩」「下午还有半天」）。结果放在行程板的「临时安排」里，不覆盖正式行程。不知道游客在哪就先问位置，不要猜。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["location"], "properties": {
            "location": {"type": "string", "minLength": 1, "maxLength": 40},
            "hours": {"type": "number", "minimum": 1, "maximum": 8, "description": "可用小时数，默认 3"},
            "kind": {"type": "string", "enum": ["any", "sight", "food", "indoor"]},
            "end_at": {"type": "string", "description": "最后要到达的地点（可选，如酒店、车站）"},
            "exclude": {"type": "array", "maxItems": 8, "items": {"type": "string"}}}}},
    "get_trip": {
        "description": "读取本会话当前的正式行程（每天的站点、时间、起止点）。修改行程前、或游客问「我的行程」时使用。",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}}},
    "plan_trip": {
        "description": "新建武汉行程（会替换当前行程）。时间、交通由排程器计算，回答时逐字使用返回的 summary_lines。不确定的条件用合理默认值，不要为此反复追问。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["days"], "properties": {
            "days": {"type": "integer", "minimum": 1, "maximum": 5},
            "start_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$", "description": "第 1 天的日期 YYYY-MM-DD；游客说了日期（如「明天」「12 月 17 日」「周六」）就换算后填，用于避开闭馆日"},
            "meals": {"type": "boolean", "description": "是否自动留午饭（默认 true：中午没有吃饭的站时，加一个顺路的美食街）"},
            "start": {"type": "string", "description": "每天出发时间 HH:MM，默认 09:00；只玩下午就填 13:00 等"},
            "end": {"type": "string", "description": "每天最晚结束时间 HH:MM，默认 18:00"},
            "stay": {"type": "string", "description": "住处或每天的出发/回程地点（地点名），没有就不填"},
            "interests": {"type": "string", "maxLength": 80, "description": "兴趣或主题，如「老建筑 过早」「第一次来 经典」"},
            "must": {"type": "array", "maxItems": 8, "items": {"type": "object", "additionalProperties": False, "required": ["place"],
                     "properties": {"place": {"type": "string"}, "day": {"type": "integer", "minimum": 1, "maximum": 5}}}},
            "avoid": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            "pace": {"type": "string", "enum": ["normal", "relaxed"], "description": "relaxed：老人小孩、怕累，少站少走"},
            "max_walk_m": {"type": "integer", "minimum": 200, "maximum": 5000, "description": "每段步行上限（米），只在游客明确提出时填"}}}},
    "edit_trip": {
        "description": "修改已有行程的某一天：推迟/提前出发、改起止时间、删站、加站、换站，把某一站挪到上午/下午/傍晚/指定时间之后（move_stop）、改当天出发地或结束地（set_origin / set_destination，如「从酒店出发」「最后到汉口站赶火车」）、改某站停留时长（set_duration）、按顺路重新规划整天顺序（reoptimize，如「太绕了」「重新排一下」）、把某站挪到另一天（move_to_day，place + to_day）、两天对调（swap_days，to_day）、设这一天的日期（set_date，用于避开闭馆日）。move_stop、改起终点都会自动按顺路重排全天顺序，其余站点保留。游客说「X 不想早上去，换到下午」用 move_stop，不要改出发时间。未提到的站点保留。排不下时会返回真实冲突，如实告诉游客并给出选项。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["day", "actions"], "properties": {
            "day": {"type": "integer", "minimum": 1, "maximum": 5},
            "actions": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "object", "additionalProperties": False,
                        "required": ["type"], "properties": {
                            "type": {"type": "string", "enum": ["delay_start", "advance_start", "set_start", "set_end", "remove_stop", "add_stop", "replace_stop", "move_stop",
                                                              "set_origin", "set_destination", "set_duration", "reoptimize",
                                                              "move_to_day", "swap_days", "set_date"]},
                            "to_day": {"type": "integer", "minimum": 1, "maximum": 5, "description": "move_to_day / swap_days 用：目标天"},
                            "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$", "description": "set_date 用：这一天的日期"},
                            "period": {"type": "string", "enum": ["morning", "afternoon", "evening"], "description": "move_stop 用：挪到上午 / 下午 / 傍晚"},
                            "minutes": {"type": "integer", "minimum": 5, "maximum": 480},
                            "time": {"type": "string", "description": "HH:MM；move_stop 时表示最早几点开始这一站"},
                            "place": {"type": "string"},
                            "with_place": {"type": "string"},
                            "duration_minutes": {"type": "integer", "minimum": 15, "maximum": 360, "description": "set_duration 用：这一站停留多少分钟"}}}}}}},
    "multi_plan": {
        "description": "同时交付多套备选行程并比较（如「一份一日游和一份两日游，比较一下」），或修改、比较、选用已交付的备选方案时使用。把游客的原话完整传入；结果会显示在行程板的方案与比较页。普通的单套行程用 plan_trip。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["request"],
                       "properties": {"request": {"type": "string", "minLength": 2, "maxLength": 600}}}},
    "remember": {
        "description": "记住游客在本次对话中明确说出的信息（称呼、住处、同行人、偏好、到达时间），之后的推荐与行程会参考。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["field", "value"], "properties": {
            "field": {"type": "string", "enum": ["name", "stay", "companions", "preference", "arrival", "other"]},
            "value": {"type": "string", "minLength": 1, "maxLength": 100}}}},
    "read_skill": {
        "description": "读取一份接待方法说明（索引见系统提示）。处理对应类型的请求前可以先读。",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["id"],
                       "properties": {"id": {"type": "string", "maxLength": 40}}}},
}
TOOL_DEFS = [{"type": "function", "function": {"name": n, "description": s["description"], "parameters": s["parameters"]}}
             for n, s in SCHEMAS.items()]
VALIDATORS = {n: Draft202012Validator(s["parameters"]) for n, s in SCHEMAS.items()}


def skill_index():
    rows = []
    for path in sorted(SKILL_DIR.glob("*.md")):
        head = path.read_text("utf8").split("\n", 3)
        rows.append({"id": path.stem, "summary": head[1].strip("# ").strip() if len(head) > 1 else path.stem})
    return rows


class Toolbox:
    def __init__(self, agent, draft, trace):
        self.agent, self.draft, self.trace = agent, draft, trace
        self.refs = {}
        self.mode = None
        self.preview = None
        self.deliverables = None

    # ── dispatch ──────────────────────────────────────────────────────────
    def call(self, name, args):
        if name not in SCHEMAS:
            return {"ok": False, "error": f"没有名为 {name} 的工具"}
        error = next(VALIDATORS[name].iter_errors(args), None)
        if error:
            return {"ok": False, "error": f"参数不符合要求：{'.'.join(map(str, error.path)) or '参数'} {error.message}"}
        try:
            return getattr(self, name)(**args)
        except Invalid as exc:
            return {"ok": False, "error": str(exc)}

    # ── read tools ────────────────────────────────────────────────────────
    def search_knowledge(self, query, topic="any", k=5):
        cats = sorted({c for v in TOPICS.values() for c in v}) if topic == "any" else TOPICS[topic]
        rows = self.agent.kb.search(query, cats, k)
        # Reviewed official facts (deadlines, schedule, venue) ride along for their own topic.
        curated = [d for d in self.agent.kb.curated if d["category"] in cats and d not in rows]
        if topic in ("saig", "community", "spu"):
            rows = rows + curated[:3]
        out = []
        for d in rows:
            ref = next((r for r, doc in self.refs.items() if doc["id"] == d["id"]), None)
            if not ref:
                ref = f"S{len(self.refs) + 1}"
                self.refs[ref] = d
            out.append({"ref": ref, "title": d.get("title", ""), "locator": d.get("locator"), "text": d["text"][:520]})
        self.trace.append({"tool": "wuhan" if topic in ("any", "wuhan") else topic, "query": query, "hits": [d["id"] for d in rows]})
        return {"ok": True, "results": out, "note": "只依据这些结果回答，句末标用到的编号如 [S1]。结果里没有的内容（名称全称、数字、日期等）不要凭记忆补充，直说官方资料没有记载。"}

    def read_source(self, ref):
        doc = self.refs.get(ref)
        if not doc:
            return {"ok": False, "error": f"本轮没有检索到 {ref}"}
        return {"ok": True, "ref": ref, "title": doc.get("title"), "text": doc["text"][:2500]}

    def find_place(self, name):
        hit, near = resolve(name)
        names = [hit] if hit else near
        found = []
        for n in names[:5]:
            p = PLACES[n]
            found.append({"name": n, "plannable": bool(p.get("minutes")), "area": p.get("area"), "zone": p.get("zone"),
                          "suggested_minutes": p.get("minutes"), "metro": _metro(n),
                          "map_url": "https://uri.amap.com/search?keyword=" + n + "&city=武汉"})
        if not found:
            atlas = [r for r in ATLAS if name in r["name"]][:3]
            found = [{"name": r["name"], "plannable": False, "area": r.get("district"), "note": "在地图目录中，可浏览，暂不能自动排程"} for r in atlas]
        self.trace.append({"tool": "location", "query": name, "result": [f["name"] for f in found]})
        return {"ok": True, "exact": bool(hit), "places": found}

    def get_weather(self, days=3):
        data = forecast()
        if not data:
            return {"ok": False, "error": "天气服务暂时连不上", "hint": "如实告诉游客暂时查不到天气，建议出发前看手机天气。"}
        self.trace.append({"tool": "weather", "query": f"{days} 天"})
        return {"ok": True, "now": data["now"], "days": data["days"][:days], "source": data["source"],
                "note": "天气是预报，可能变化；不要编造预报里没有的数据。"}

    def arrival_guide(self, gateway, destination="智民里"):
        hit, _ = resolve(destination or "智民里")
        place = hit or (destination or "").strip() or "智民里"
        target = VENUE_STATIONS.get(place) or ACCESS.get(place)
        if not target and destination and destination.rstrip("站") in METRO_STATIONS:
            place, target = destination, destination.rstrip("站")
        if not target:
            return {"ok": False, "error": f"没找到「{destination}」附近的地铁站", "hint": "可以先用 find_place 确认地点名称。"}
        start = GATEWAYS[gateway]
        route = metro_route(start, target)
        if not route:
            return {"ok": False, "error": f"{gateway}到{target}站暂时算不出地铁线路"}
        minutes, hops = route
        name = lambda st: st if st.endswith("站") else st + "站"
        legs = [f"{name(hops[0][0])}上{hops[0][1]}"] + [f"在{name(st)}换乘{line}" for st, line in hops[1:]]
        self.trace.append({"tool": "arrival", "query": f"{gateway}→{place}"})
        return {"ok": True, "from": gateway, "to": place, "metro_steps": legs, "get_off": name(target),
                "transfers": len(hops) - 1, "metro_minutes_estimate": minutes,
                "map_url": f"https://uri.amap.com/search?keyword={place}&city=武汉",
                "note": "地铁时间是按站数估算的车上时间，不含进出站和候车（另加 10–20 分钟）。票价、末班车时间资料里没有，不要编。行李多或深夜到达可建议打车，但不要给具体车费。"}

    # ── right-now recommendations ─────────────────────────────────────────
    def _here(self, location):
        hit, near = resolve(location)
        if hit:
            return hit
        station = location.strip().rstrip("站")
        stops = [n for n, st in ACCESS.items() if n in PLACES and station and (st == station or station in st)]
        if stops:
            return stops[0]
        raise Invalid(f"没认出「{location}」在哪。" + (f"是不是 {'、'.join(near)}？" if near else "") + "请告诉游客说一个附近的地铁站或地标。")

    def _candidates(self, here, kind, exclude, now_min, today, radius=5.0):
        c = {**new_contract(), "date": today}
        out = []
        for n, p in PLACES.items():
            if not p.get("minutes") or n == here or n in exclude or n in ("智民里",):
                continue
            if kind == "food" and n not in FOOD:
                continue
            if kind == "sight" and n in FOOD:
                continue
            if kind == "indoor" and not (HOURS.get(n, {}).get("open") and not HOURS[n].get("all_day")) and "博物馆" not in n and "美术馆" not in n:
                continue
            km = straight_km(here, n)
            if km is None or km > radius:
                continue
            lo, hi = window_of(c, n)
            last = HOURS.get(n, {}).get("last_entry")
            shut = closed_on(c, n)
            open_now = not shut and lo <= now_min + 20 and now_min < hi - 30 and (not last or now_min <= _clock(last))
            out.append({"name": n, "km": round(km, 1), "open_now": open_now, "closed_today": bool(shut),
                        "hours": None if not HOURS.get(n) else ("全天开放" if HOURS[n].get("all_day") else f"{HOURS[n]['open']}—{HOURS[n]['close']}"),
                        "booking": bool(HOURS.get(n, {}).get("booking")), "suggested_minutes": p["minutes"], "metro": _metro(n)})
        return sorted(out, key=lambda r: (not r["open_now"], r["km"]))

    @staticmethod
    def _now():
        now = _dt.now(_tz(_td(hours=8)))
        return now.date().isoformat(), now.hour * 60 + now.minute

    def nearby(self, location, kind="any", exclude=()):
        here = self._here(location)
        today, now_min = self._now()
        banned = {self._place(x) if resolve(x)[0] else x for x in exclude}
        rows = [r for r in self._candidates(here, kind, banned, now_min, today) if r["open_now"]][:6]
        self.trace.append({"tool": "location", "query": f"附近 {here}", "result": [r["name"] for r in rows]})
        return {"ok": True, "from": here, "now": hhmm(now_min), "places": rows,
                "note": "只推荐 open_now 为真的；距离是直线公里数。需要预约的要提醒。资料没写开放时间的（hours 为空）提醒以现场为准。"}

    def plan_now(self, location, hours=3, kind="any", end_at=None, exclude=()):
        here = self._here(location)
        today, now_min = self._now()
        start = ((now_min + 14) // 15) * 15
        end = min(start + int(hours * 60), 22 * 60)
        if end - start < 60:
            raise Invalid("现在离 22:00 不到 1 小时，建议就近吃点东西、早点休息，不再排新的景点。")
        banned = {self._place(x) if resolve(x)[0] else x for x in exclude}
        pool = [r["name"] for r in self._candidates(here, kind, banned, start, today) if r["open_now"]][:7]
        if not pool:
            return {"ok": False, "error": "附近 5 公里内此刻没有开着、可排程的地方", "hint": "如实说明，建议游客换个片区或改天。"}
        c = {**new_contract(), "start": start, "end": end, "origin": here, "date": today,
             "destination": self._place(end_at) if end_at else None}
        best = None
        most = 2 if kind == "food" else 4
        for size in range(min(most, len(pool)), 0, -1):
            for group in _combos(pool, size):
                if sum(n in FOOD for n in group) > (2 if kind == "food" else 1):
                    continue
                found = reorder(c, list(group), candidates=4) if size > 1 else None
                if size == 1:
                    proof = evaluate(c, list(group))
                    found = None if proof["violations"] else (list(group), proof)
                if not found:
                    continue
                order, proof = found
                travel = sum(s["leg"] for s in proof["stops"]) + proof["last_leg"]
                rank = (-len(order), travel)
                if best is None or rank < best[0]:
                    best = (rank, order, proof)
            if best:
                break
        if not best:
            return {"ok": False, "error": "这段时间里排不进附近的景点", "hint": "如实说明，可以只推荐一个最近的地方（用 nearby）。"}
        _, order, proof = best
        card = {"contract": c, "order": order, "audit": proof, "diff": {}, "guide": None, "guide_source": None}
        self.preview = {"1": card}
        self.mode = "preview"
        self.trace.append({"tool": "location", "query": f"临时安排 {here}", "result": order})
        said = location.strip()
        line = day_lines({"1": card})[0].replace("第1天：", f"今天 {hhmm(start)} 从{said if said != here else here}出发：")
        return {"ok": True, "summary_line": line, "opening_notes": opening_notes({"1": card}) or None,
                "reminder": "逐字给出 summary_line，一句话说为什么这样排；说明已放在行程板「临时安排」，不影响正式行程。"}

    def get_trip(self):
        days = self.draft.get("days") or {}
        if not days:
            return {"ok": True, "has_trip": False, "note": "当前还没有行程。"}
        return {"ok": True, "has_trip": True, "summary_lines": day_lines(days),
                "days": {k: {"start": hhmm(c["contract"]["start"]), "end": hhmm(c["contract"]["end"]),
                             "origin": c["contract"].get("origin"), "stops": c["order"]} for k, c in days.items()}}

    def read_skill(self, id):
        path = SKILL_DIR / f"{re.sub(r'[^a-z0-9-]', '', id)}.md"
        if not path.exists():
            return {"ok": False, "error": "没有这份方法说明", "available": [s["id"] for s in skill_index()]}
        return {"ok": True, "id": path.stem, "text": path.read_text("utf8")[:4000]}

    # ── write tools ───────────────────────────────────────────────────────
    def _place(self, name):
        hit, near = resolve(name)
        if not hit:
            raise Invalid(f"「{name}」不在可排程的地点目录里。相近的有：{'、'.join(near) or '无'}。请换成目录里的地点，或先用 find_place 查。")
        return hit

    def _commit(self, days, mode):
        if self.draft.get("days"):
            self.draft["past_days"] = (self.draft.get("past_days", []) + [deepcopy(self.draft["days"])])[-8:]
        self.draft.setdefault("first_days", deepcopy(self.draft.get("days") or days))
        self.draft["days"] = days
        self.draft.pop("pending_days", None)
        self.mode = mode

    def _fill_day(self, key, card, op, used, limit=3):
        """A day that ends with 2h+ unused gets nearby stops (<=4 km from the route), re-planned and audited each time."""
        c = card["contract"]
        skip = set(op.get("exclude", [])) | set(used) | {"智民里", "光谷空轨"}
        for _ in range(limit):
            free = c["end"] - card["audit"]["arrival"]
            if free < 120 or len(card["order"]) >= c["max_stops"]:
                break
            near = []
            for n, p in PLACES.items():
                if not p.get("minutes") or n in card["order"] or n in skip or n in FOOD:
                    continue
                d = min((straight_km(n, m) or 99) for m in card["order"])
                if d <= 4 and p["minutes"] <= free - 30:
                    near.append((d, n))
            added = False
            for _, n in sorted(near)[:3]:
                edit = {"day": int(key), "query": "", "set": {}, "require": [n], "add": list(card["order"]),
                        "mobility": deepcopy(c.get("mobility") or {"rules": []}), "avoid": op.get("avoid", []), "reoptimize": True}
                try:
                    card = self.agent.day(key, edit, card, self.trace)
                    c = card["contract"]
                    added = True
                    break
                except Invalid:
                    skip.add(n)
            if not added:
                break
        return card

    def _add_lunch(self, key, card, op, used):
        """New plans that span lunch get a food street around noon (nearest to where the visitor is then)."""
        noon = next((s for s in card["audit"]["stops"] if s["end"] >= 12 * 60), card["audit"]["stops"][-1] if card["audit"]["stops"] else None)
        if not noon:
            return card, None
        options = sorted((f for f in FOOD if f not in card["order"] and f not in used and f not in op.get("exclude", [])),
                         key=lambda f: straight_km(noon["place"], f) or 99)
        for food in options[:2]:
            edit = {"day": int(key), "query": "", "set": {"windows": {food: [hhmm(LUNCH[0]), hhmm(LUNCH[1])]}},
                    "require": [food], "add": list(card["order"]), "mobility": deepcopy(card["contract"].get("mobility") or {"rules": []}),
                    "avoid": op.get("avoid", []), "reoptimize": True}
            try:
                return self.agent.day(key, edit, card, self.trace), food
            except Invalid:
                continue
        return card, None

    def plan_trip(self, days, start="09:00", end="18:00", stay=None, interests="", must=(), avoid=(), pace="normal", max_walk_m=None,
                  start_date=None, meals=True):
        s, e = _clock(start), _clock(end)
        if e - s < 120:
            raise Invalid("每天可用时间不足 2 小时，无法排程，请放宽结束时间或提前出发。")
        home = self._place(stay) if stay else None
        wanted = [(self._place(m["place"]), m.get("day")) for m in must]
        banned = [self._place(a) for a in avoid]
        rules = []
        if max_walk_m:
            rules.append({"field": "单段步行上限米", "subject": "", "value": max_walk_m, "quote": f"每段步行不超过{max_walk_m}米"})
        mobility = {"rules": rules, "default_preference": "less_walk" if pace == "relaxed" else "fastest"}
        template = None
        # Multi-day trips without must-visits follow the handbook's own day-by-day route.
        if not wanted and days in (2, 3):
            template = {2: "metro-two", 3: "metro-three"}[days]
        assigned, turn = {d: [] for d in range(1, days + 1)}, 0
        for p, dd in wanted:
            if dd and 1 <= dd <= days:
                assigned[dd].append(p)
            else:  # no day given: spread over the days in order
                assigned[1 + turn % days].append(p); turn += 1
        result, used, meal_notes = {}, set(), []
        for d in range(1, days + 1):
            req = list(dict.fromkeys(assigned[d]))
            op = {"day": d, "query": interests or "第一次来武汉 经典 景点", "set": {"start": hhmm(s), "end": hhmm(e)},
                  "require": req, "exclude": banned, "mobility": deepcopy(mobility), "avoid": sorted(used - set(req))}
            if home:
                op["set"].update(origin=home, destination=home)
            if pace == "relaxed":
                op["set"]["max_stops"] = 4
            if template:
                op["template"] = template
            if start_date:
                op["set"]["date"] = (_date.fromisoformat(start_date) + _td(days=d - 1)).isoformat()
            card = self.agent.day(str(d), op, None, self.trace)
            if pace != "relaxed":
                card = self._fill_day(str(d), card, op, used)
            if meals and s <= 11 * 60 + 30 and e >= LUNCH[1] and not lunch_stop(card):
                card, food = self._add_lunch(str(d), card, op, used)
                if food:
                    meal_notes.append(f"第{d}天中午加了{food}吃午饭")
            lunch = lunch_stop(card)
            if meals and s <= 11 * 60 + 30 and e >= LUNCH[1] and not lunch:
                meal_notes.append(f"第{d}天中午没有排进吃饭的站，建议在 12:00 前后就近吃")
            result[str(d)] = card
            used.update(card["order"])
        review = trip_review(result)
        self.trace.append({"step": "trip_review", "audit": review})
        self._commit(result, "plan")
        notes = []
        for k, c in result.items():
            if c.get("guide_source"):
                notes.append(f"第{k}天参考《{c['guide_source']['title']}》")
        out = {"ok": True, "summary_lines": day_lines(result), "notes": notes,
               "reminder": "回答时逐字列出 summary_lines（每行以「第N天：」开头），再用一两句说明亮点；交通与每站时间已显示在行程板上。"}
        if meal_notes:
            out["meals"] = meal_notes
        hours = opening_notes(result)
        if hours:
            out["opening_notes"] = hours
            out["reminder"] += "opening_notes 里需要预约或有闭馆日的，挑最要紧的一两条用一句话提醒。"
        if not start_date:
            out["reminder"] += "不知道出行日期时，有闭馆日的站要提醒游客避开那天，或问一句哪天去。"
        return out

    def _cross_day(self, day, action):
        """Move one stop to another day, or swap two days; both days are re-planned and audited."""
        days = self.draft.get("days") or {}
        a, b = str(day), str(action.get("to_day") or "")
        if b not in days or a not in days or a == b:
            raise Invalid(f"需要两个已有的不同日期。现有：{'、'.join(f'第{k}天' for k in sorted(days, key=int))}")
        new = dict(days)
        def rerun(key, stops, base, extra=None):
            c = days[key]["contract"]
            op = {"day": int(key), "query": "", "set": {}, "mobility": deepcopy(c.get("mobility") or {"rules": []}),
                  "add": stops, "remove": [n for n in days[key]["order"] if n not in stops],
                  "unrequire": [n for n in c.get("must", []) if n not in stops], "reoptimize": True,
                  "avoid": sorted({n for k, v in days.items() if k not in (a, b) for n in v["order"]})}
            if extra:
                op["require"] = [extra]
            return self.agent.day(key, op, base, self.trace)
        if action["type"] == "move_to_day":
            p = self._place(action.get("place", ""))
            if p not in days[a]["order"]:
                raise Invalid(f"第{a}天没有「{p}」。当天站点：{'、'.join(days[a]['order'])}")
            new[b] = rerun(b, days[b]["order"] + [p], days[b], extra=p)
            rest = [n for n in days[a]["order"] if n != p]
            if rest:
                new[a] = rerun(a, rest, days[a])
            else:
                new.pop(a)
        else:
            # Each day keeps its own times and date; the stops trade places.
            new[a] = rerun(a, list(days[b]["order"]), days[a])
            new[b] = rerun(b, list(days[a]["order"]), days[b])
        self._commit(new, "edit")
        touched = {k: new[k] for k in (a, b) if k in new}
        return {"ok": True, "summary_lines": day_lines(touched), "opening_notes": opening_notes(touched) or None,
                "reminder": "回答时逐字给出改动的两天（以「第N天：」开头），一句话说明挪了什么。"}

    def edit_trip(self, day, actions):
        key = str(day)
        days = self.draft.get("days") or {}
        old = days.get(key)
        if not old:
            raise Invalid(f"当前行程没有第{day}天。" + ("现有：" + "、".join(f"第{k}天" for k in sorted(days)) if days else "还没有行程，请先用 plan_trip 新建。"))
        c = old["contract"]
        keep = list(old["order"])
        op = {"day": day, "query": "", "set": {}, "mobility": deepcopy(c.get("mobility") or {"rules": []}),
              "avoid": sorted({n for k, v in days.items() if k != key for n in v["order"]})}
        cross = [a for a in actions if a["type"] in ("move_to_day", "swap_days")]
        if cross:
            try:
                return self._cross_day(day, cross[0])
            except Invalid as exc:
                return {"ok": False, "error": str(exc), "unchanged": True,
                        "hint": "行程保持原样。如实告诉游客哪一天排不下，并给一个可行的替代（例如再删一站或延长那天的结束时间）。"}
        added, removed, moved = [], [], []
        for a in actions:
            t = a["type"]
            if t in ("delay_start", "advance_start"):
                if not a.get("minutes"):
                    raise Invalid("推迟或提前需要给出分钟数 minutes")
                op["set"]["start"] = hhmm(c["start"] + (a["minutes"] if t == "delay_start" else -a["minutes"]))
            elif t in ("set_start", "set_end"):
                op["set"]["start" if t == "set_start" else "end"] = hhmm(_clock(a.get("time")))
            elif t == "remove_stop":
                p = self._place(a.get("place", ""))
                if p not in keep:
                    raise Invalid(f"第{day}天没有「{p}」。当天站点：{'、'.join(keep)}")
                keep.remove(p); removed.append(p)
            elif t == "add_stop":
                p = self._place(a.get("place", ""))
                if p not in keep:
                    keep.append(p); added.append(p)
            elif t == "move_stop":
                p = self._place(a.get("place", ""))
                if p not in keep:
                    raise Invalid(f"第{day}天没有「{p}」。当天站点：{'、'.join(keep)}")
                if a.get("time"):
                    window = [_clock(a["time"]), 1439]
                else:
                    window = PERIODS.get(a.get("period"))
                    if not window:
                        raise Invalid("move_stop 需要 period（morning/afternoon/evening）或 time")
                op["set"].setdefault("windows", {})[p] = [hhmm(window[0]), hhmm(window[1])]
                op["reoptimize"] = True
                moved.append(p)
            elif t in ("set_origin", "set_destination"):
                p = self._place(a.get("place", ""))
                op["set"]["origin" if t == "set_origin" else "destination"] = p
                op["reoptimize"] = True
            elif t == "set_duration":
                p = self._place(a.get("place", ""))
                if p not in keep:
                    raise Invalid(f"第{day}天没有「{p}」。当天站点：{'、'.join(keep)}")
                if not a.get("duration_minutes"):
                    raise Invalid("set_duration 需要 duration_minutes")
                op["set"].setdefault("durations", {})[p] = a["duration_minutes"]
            elif t == "reoptimize":
                op["reoptimize"] = True
            elif t == "set_date":
                if not a.get("date"):
                    raise Invalid("set_date 需要 date（YYYY-MM-DD）")
                op["set"]["date"] = a["date"]
                op["reoptimize"] = True
            elif t == "replace_stop":
                p, q = self._place(a.get("place", "")), self._place(a.get("with_place", ""))
                if p not in keep:
                    raise Invalid(f"第{day}天没有「{p}」。当天站点：{'、'.join(keep)}")
                keep[keep.index(p)] = q; removed.append(p); added.append(q)
        # Removing and re-adding the same place in one edit means "keep it" (the model's way to move a stop).
        both = set(removed) & set(added)
        removed = [p for p in removed if p not in both]
        added = [p for p in added if p not in both]
        if removed:
            op["remove"] = removed
            op["unrequire"] = [p for p in removed if p in c.get("must", [])]
        if added:
            op["require"] = added
        op["add"] = [p for p in keep if p not in added]
        try:
            card = self.agent.day(key, op, old, self.trace)
        except Invalid as exc:
            return {"ok": False, "error": str(exc), "unchanged": True,
                    "hint": "行程保持原样。若游客已表示想轻松、少走或晚出发，直接再调用一次 edit_trip，多删一个离路线最远的站后重试，然后在回答里说明多删了哪站；只有游客明确要保留全部站点时，才把选择题交给游客。回答要完整，不要中途截断。"}
        new = {**days, key: card}
        self._commit(new, "edit")
        out = {"ok": True, "summary_lines": day_lines({key: card}), "diff": card.get("diff"),
               "reminder": "回答时逐字给出这一天的新安排（以「第N天：」开头），一句话说明改了什么。"}
        hours = opening_notes({key: card})
        if hours:
            out["opening_notes"] = hours
        gaps = idle_gaps(card)
        if gaps:
            out["free_time"] = gaps
            out["reminder"] += "free_time 是空出来的时间，顺口建议怎么用（如午饭、喝茶、附近逛逛）。"
        return out

    def multi_plan(self, request):
        # Alternatives and comparisons keep the reviewed multi-deliverable planner.
        draft, res = self.agent.execute_turn(request, self.draft)
        kernel_memory = self.draft.get("kernel")
        self.draft.clear()
        self.draft.update(draft)
        if kernel_memory is not None:
            self.draft["kernel"] = kernel_memory
        self.deliverables = res.get("deliverables")
        self.trace.extend(res.get("trace", []))
        self.mode = res.get("mode") or "compose"
        return {"ok": True, "result": res.get("answer", "")[:2500],
                "reminder": "把以上结果整理后告诉游客（保留每套方案的名称与每日站点），并提示可在行程板的「比较」页查看差异。"}

    def remember(self, field, value):
        memory = self.draft.setdefault("kernel", {}).setdefault("facts", {})
        memory[field] = value
        return {"ok": True, "remembered": {field: value}}
