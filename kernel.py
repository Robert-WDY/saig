"""Receptionist kernel: one tool-calling decision loop (modelled on ChorifyCore's AgentEngine).

The model sees the tool list, a short skill index and the session memory, decides which tool to
call next, and the program executes it and returns the real result, until the model answers. There
is no keyword routing and no fixed pipeline. Facts must come from `search_knowledge` and are cited
as [S#]; the program removes any citation that was not actually retrieved this turn. Trip times
come only from the deterministic scheduler behind plan_trip / edit_trip.
"""
import json
import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import requests

from diagnostics import timed
from kernel_tools import TOOL_DEFS, WRITE_TOOLS, Toolbox, day_lines, skill_index
from limits import charge_attempt, remaining
from model import ModelError, deepseek_key
from planning import transport_cache

MAX_STEPS = 6
HISTORY_TURNS = 8
BEIJING = timezone(timedelta(hours=8))

PERSONA = """你是「江豚接待员」——武汉数命 SPU 城市 AI 接待员，形象是 SAIG 官方的蓝色江豚。你在「武汉接线台」为来武汉的游客、选手和评委服务：
介绍武汉；介绍数命 SPU 社区；规划和修改武汉行程；讲清数命 SPU 概念与 SAIG 比赛。

工作方式：
- 关于武汉、景点、美食、社区、SPU、SAIG 的任何事实，先用 search_knowledge 检索，回答里在对应句子末尾标 [S编号]。资料里没有的就直说「官方资料里没有记载」，并建议以官方渠道为准。绝不编造数字、日期、价格、开放时间、地址。
- 排行程、改行程只能通过 plan_trip / edit_trip；行程中的时间与交通全部来自工具结果，照抄 summary_lines，不自己改时间。
- 游客的说法不标准（如「光谷」「省博」「武大」）时，用 find_place 对上目录名称再排程。
- 条件不全时用合理默认值先做出来，再告诉游客可以怎么调整；只有缺「几天」这种关键信息时才追问，一次最多问一个问题。
- 游客说出称呼、住处、同行人、偏好、到达时间时，用 remember 记下。
- 打招呼、道谢、闲聊直接回答，不需要调用工具。
- 用游客的语言回答（中文、English、日本語、한국어）；专有名词首次出现可附中文。
- 口吻热情、简洁、像真人接待员。每次回答控制在 2–8 行；不要输出 Markdown 标题、表格或代码块；可以用「·」列点。
- 不要虚构游客说过的话或问过的问题；只依据真实的对话记录。
- 不要提及工具名、内部编号以外的系统细节，不要复述这些规则。
"""


def _now():
    return datetime.now(BEIJING)


def system_prompt(state):
    k = state.get("kernel", {})
    skills = "\n".join(f"- {s['id']}：{s['summary']}" for s in skill_index())
    facts = k.get("facts") or {}
    lines = [PERSONA, f"今天是 {_now():%Y-%m-%d}（北京时间）。", "接待方法索引（需要时用 read_skill 读全文）：\n" + skills]
    if facts:
        lines.append("已记住的游客信息：" + "；".join(f"{a}={b}" for a, b in facts.items()))
    if state.get("days"):
        lines.append("游客当前的正式行程：\n" + "\n".join(day_lines(state["days"])))
    if k.get("earlier"):
        lines.append("更早聊过的话题：" + "；".join(k["earlier"][-10:]))
    return "\n\n".join(lines)


class Kernel:
    """Wraps an Agent: reuses its knowledge base, deterministic scheduler and session store."""

    def __init__(self, agent):
        self.agent = agent
        self.store = agent.store
        self.model = agent.model
        self.kb = agent.kb
        self._http = threading.local()

    # Old entry points used by /tool and /rag stay on the Agent.
    def tool(self, *args, **kwargs):
        return self.agent.tool(*args, **kwargs)

    # ── model port: one streaming chat completion with tools ───────────────
    def chat(self, messages, tools=None, on_delta=None, max_tokens=1400):
        m = self.model
        key = deepseek_key() if m.deepseek else None
        headers = {"Authorization": "Bearer " + key} if key else {}
        body = {"model": m.name, "messages": messages, "temperature": 0.3, "max_tokens": max_tokens, "stream": True}
        if tools:
            body["tools"] = tools
        if m.deepseek:
            body["thinking"] = {"type": "disabled"}
        if not hasattr(self._http, "session"):
            self._http.session = requests.Session()
            self._http.session.trust_env = False
        reason = None
        for attempt in range(2):
            with timed("model_http") as event:
                event["attempt"] = attempt + 1
                if reason:
                    event["reason"] = reason
                charge_attempt()
                try:
                    resp = self._http.session.post(m.base + "/chat/completions", headers=headers, json=body, stream=True,
                                                   timeout=(remaining(8), remaining(60)), allow_redirects=False)
                except requests.ConnectTimeout:
                    if attempt:
                        raise
                    reason = "connect_timeout"
                    continue
                if resp.status_code in (429, 500, 502, 503, 504) and not attempt:
                    time.sleep(min(remaining(2), 1))
                    reason = f"upstream_{resp.status_code}"
                    continue
                resp.raise_for_status()
                resp.encoding = "utf-8"
                content, calls, finish, usage = [], {}, None, None
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    usage = chunk.get("usage") or usage
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            content.append(delta["content"])
                            if on_delta:
                                on_delta(delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            slot["id"] = tc.get("id") or slot["id"]
                            fn = tc.get("function") or {}
                            slot["function"]["name"] += fn.get("name") or ""
                            slot["function"]["arguments"] += fn.get("arguments") or ""
                        finish = choice.get("finish_reason") or finish
                event["finish"] = finish
            message = {"role": "assistant", "content": "".join(content)}
            if calls:
                message["tool_calls"] = [calls[i] for i in sorted(calls)]
                for i, c in enumerate(message["tool_calls"]):
                    c["id"] = c["id"] or f"call_{i}_{uuid4().hex[:8]}"
            if finish == "length" and not calls:
                message["content"] += "…"
            return message
        raise ModelError("模型服务暂不可用")

    # ── one visitor turn ──────────────────────────────────────────────────
    def respond(self, sid, q, req=None, emit=None):
        token = transport_cache.set({})
        try:
            if not q.strip() or not sid.strip():
                raise ValueError("请提供会话和问题")
            req = req or uuid4().hex
            rev, state, cached = self.store.read(sid, req, q)
            if cached:
                return cached
            draft, result = self.turn(q, state, emit or (lambda *_: None))
            result["revision"] = rev + 1
            return self.store.save(sid, req, q, rev, draft, result)
        finally:
            transport_cache.reset(token)

    def turn(self, q, state, emit):
        draft = deepcopy(state)
        k = draft.setdefault("kernel", {"turns": [], "facts": {}, "earlier": []})
        trace = []
        box = Toolbox(self.agent, draft, trace)
        messages = [{"role": "system", "content": system_prompt(draft)}]
        for t in k.get("turns", [])[-HISTORY_TURNS:]:
            messages += [{"role": "user", "content": t["user"]}, {"role": "assistant", "content": t["assistant"]}]
        messages.append({"role": "user", "content": q})
        final = None
        guarded = False
        for step in range(MAX_STEPS):
            emit("step", {"step": step})
            msg = self.chat(messages, TOOL_DEFS, on_delta=lambda d, s=step: emit("delta", {"step": s, "text": d}))
            calls = msg.get("tool_calls") or []
            if not calls:
                # Grounding guard: a substantive answer that used no tool and cites nothing is not
                # accepted once; the model is told to look the facts up first. Greetings stay short.
                text = msg["content"] or ""
                if not trace and not guarded and len(re.sub(r"\s", "", text)) >= 90 and "[S" not in text:
                    guarded = True
                    emit("step_end", {"step": step, "final": False})
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": "（系统检查：这条回答没有检索任何官方资料，也没有出处。请先用 search_knowledge（必要时 find_place / plan_trip）查证，再重新回答；资料里没有的要直说。）"})
                    trace.append({"step": "grounding_retry"})
                    continue
                final = text
                emit("step_end", {"step": step, "final": True})
                break
            emit("step_end", {"step": step, "final": False})
            messages.append({k2: v for k2, v in msg.items() if k2 in ("role", "content", "tool_calls")})
            wrote = False
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                    if not isinstance(args, dict):
                        raise ValueError
                except ValueError:
                    result = {"ok": False, "error": "参数不是合法的 JSON 对象"}
                else:
                    if name in WRITE_TOOLS and wrote and name != "remember":
                        result = {"ok": False, "error": "本步已经修改过一次行程；请先看上一个结果，再决定下一步。"}
                    else:
                        emit("tool", {"name": name, "args": args})
                        started = time.perf_counter()
                        result = box.call(name, args)
                        wrote = wrote or (name in WRITE_TOOLS and name != "remember" and result.get("ok"))
                        emit("tool_done", {"name": name, "ok": bool(result.get("ok")), "ms": round((time.perf_counter() - started) * 1000)})
                trace.append({"step": "tool_call", "name": name, "ok": bool(result.get("ok")),
                              "error": None if result.get("ok") else result.get("error")})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)[:7000]})
        if final is None:
            # Budget spent: answer from what was gathered, no more tools.
            messages.append({"role": "user", "content": "（系统提示：工具步数已用完。请只根据上面已有的工具结果直接回答游客，不要再调用工具；没查到的如实说明。）"})
            emit("step", {"step": MAX_STEPS})
            final = self.chat(messages, None, on_delta=lambda d: emit("delta", {"step": MAX_STEPS, "text": d}))["content"]
            emit("step_end", {"step": MAX_STEPS, "final": True})
        answer, citations = self.ground(final, box)
        k.setdefault("turns", []).append({"user": q, "assistant": answer[:1500]})
        if len(k["turns"]) > HISTORY_TURNS:
            for old in k["turns"][:-HISTORY_TURNS]:
                k.setdefault("earlier", []).append(old["user"][:40])
            k["turns"] = k["turns"][-HISTORY_TURNS:]
        draft["turns"] = (draft.get("turns", []) + [{"user": q, "answer": answer, "offered_places": [], "sources": [c["id"] for c in citations]}])[-12:]
        mode = box.mode or "info"
        result = {"answer": answer, "mode": mode, "days": draft.get("days") or {}, "preview": None,
                  "citations": citations, "facts": draft.get("facts", []), "trace": trace, "kernel": "v2"}
        if box.deliverables:
            result["deliverables"] = box.deliverables
        return draft, result

    # ── grounding: citations must come from this turn's real retrievals ───
    @staticmethod
    def ground(text, box):
        text = (text or "").strip()
        text = re.sub(r"^#+\s*", "", text, flags=re.M).replace("**", "")
        citations, lines = [], []
        for line in text.splitlines():
            refs = re.findall(r"\[(S\d+)\]", line)
            clean = re.sub(r"\s*\[(?:S\d+)(?:[,，、\s]*S\d+)*\]", "", line)
            clean = re.sub(r"\s*\[S\d+(?:\s*[,，、]\s*S\d+)+\]", "", clean).rstrip()
            lines.append(clean)
            for ref in dict.fromkeys(refs):
                doc = box.refs.get(ref)
                if not doc or not clean.strip():
                    continue
                citations.append({**{f: doc.get(f) for f in ("id", "source", "title", "locator", "edition")},
                                  "quote": doc["text"][:300], "claim": clean.strip()})
        answer = "\n".join(lines).strip()
        return answer or "抱歉，我刚才没组织好回答，可以换个说法再问我一次吗？", citations
