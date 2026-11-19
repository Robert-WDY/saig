"""Normalize source-backed quantities after the model selects their semantic role."""
import re

DIGITS={n:i for i,n in enumerate("零一二三四五六七八九")}
DIGITS.update({"两":2,"〇":0})
UNITS={"十":10,"百":100,"千":1000}
NUM=r"[零〇一二两三四五六七八九十百千\d]+"

def number(s):
    if s.isdecimal():return int(s)
    if not any(c in UNITS for c in s):
        return int("".join(str(DIGITS[c]) for c in s))
    total=current=0
    for c in s:
        if c in UNITS:
            total+=(current or 1)*UNITS[c]
            current=0
        else:
            current=DIGITS[c]
    return total+current

def durations(text):
    values=[]
    hours=rf"(?:(?P<dec>\d+(?:\.\d+)?)|(?P<h>{NUM}|半)个?(?P<half1>半)?)(?:个)?(?:小时|钟头)(?P<half>半)?"
    for part in re.finditer(rf"(?:{hours})?(?:(?P<q>{NUM})刻钟)?(?:(?P<m>{NUM})分钟)?",text):
        dec,h,half1,half,q,m=part.group("dec","h","half1","half","q","m")
        if not (dec or h or q or m): continue
        base=round(float(dec)*60) if dec else 30 if h=="半" else 60*number(h) if h else 0
        values.append(base+(30 if half1 or half else 0)+15*(number(q) if q else 0)+(number(m) if m else 0))
    return values


def clocks(text):
    """Locate literal times; a role is assigned separately from each mention by the model."""
    pattern=rf"(?P<period>凌晨|清晨|早上|上午|中午|下午|傍晚|晚上)?\s*(?P<h>{NUM})\s*(?:(?:点|时)(?:(?P<half>半)|(?P<quarter>[一三])刻|(?P<m>{NUM})分?)?|[:：](?P<digit>\d{{2}}))"
    result=[]
    for m in re.finditer(pattern,text):
        hour=number(m["h"])
        minute=30 if m["half"] else 15*number(m["quarter"]) if m["quarter"] else number(m["m"] or m["digit"]) if m["m"] or m["digit"] else 0
        if m["period"] in ("中午","下午","傍晚","晚上") and hour<12:hour+=12
        if hour<24 and minute<60:result.append((m.start(),m.end(),f"{hour:02d}:{minute:02d}"))
    return result
