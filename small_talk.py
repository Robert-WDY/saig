"""Conversational turns that carry no lookup or itinerary task: greetings, thanks, who-are-you, out-of-scope asks.

The reply may describe what the receptionist can do and steer the visitor, but it never states
facts about Wuhan, the community or SAIG. Those always go through cited retrieval.
"""
import re
from semantics import obj, STRING

PERSONA = """你是「江豚接待员」，武汉数命 SPU 城市 AI 接待员，形象是赛事官方的蓝色江豚。
你能做四件事：介绍武汉（三镇、历史、美食、景点）；介绍数命 SPU 社区；规划和随时修改武汉一到三日行程；讲解数命 SPU 概念与 SAIG 比赛怎么参加。
现在游客说的话不需要查资料或排行程，可能是打招呼、道谢、问你是谁/能做什么、闲聊，或问了你资料里没有的事（实时天气、酒店、票价、预订等）。
要求：口语、热情、简短，最多三句话，80 字以内。不要编造任何具体事实、数字、地址、时间或价格。
资料没有的事情坦白说暂时查不到，并建议游客以官方渠道为准。最后用一句话给出一个可以马上问你的具体例子。
游客用英文就用英文回答。只返回给游客的话。"""


def english(text):
    letters = re.findall(r"[A-Za-z]", text or "")
    han = re.findall(r"[一-鿿]", text or "")
    return len(letters) >= 6 and len(letters) > 3 * len(han)


def small_talk(model, question, state):
    recent = [{"游客": t.get("user", ""), "接待员": t.get("answer", "")[:160]} for t in state.get("turns", [])[-2:]]
    context = {"游客本轮": question, "近期对话": recent, "已有行程天数": len(state.get("days", {}))}
    try:
        reply = model.ask(PERSONA, context, 220, obj({"回复": STRING}))["回复"].strip()
    except Exception:
        reply = ""
    if reply:
        return reply
    if english(question):
        return "Hi! I'm the porpoise receptionist for Wuhan. Ask me about the city, the Shuming SPU community, a trip plan or the SAIG contest."
    return "你好呀！我是江豚接待员，可以给你讲讲武汉、介绍数命 SPU 社区、排几天行程，或者说说 SAIG 怎么参加。试试问我：第一次来武汉，帮我排个两日游？"
