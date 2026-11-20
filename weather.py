"""Wuhan weather for trip advice: a domestic forecast feed (15 days, sunrise/sunset, AQI) with wttr.in as
fallback. Cached for 30 minutes; any failure returns None so the receptionist simply says it can't check."""
import threading
import time

import requests

FEEDS = ("http://t.weather.itboy.net/api/weather/city/101200101", "https://wttr.in/Wuhan?format=j1&lang=zh")
_cache = {"at": 0.0, "value": None}
_lock = threading.Lock()


def _itboy(data):
    d = data["data"]
    days = [{"date": f["ymd"], "week": f["week"], "weather": f["type"],
             "high_c": int(f["high"].split()[-1].rstrip("℃")), "low_c": int(f["low"].split()[-1].rstrip("℃")),
             "wind": f["fx"] + f["fl"], "sunrise": f["sunrise"], "sunset": f["sunset"], "aqi": f.get("aqi")}
            for f in d["forecast"]]
    return {"now": {"temp_c": float(d["wendu"]), "humidity": d["shidu"], "air": d["quality"]}, "days": days,
            "source": "中国天气网数据（itboy 转发）"}


def _wttr(data):
    cur = data["current_condition"][0]
    days = [{"date": w["date"], "weather": w["hourly"][4]["lang_zh"][0]["value"] if w["hourly"][4].get("lang_zh") else w["hourly"][4]["weatherDesc"][0]["value"],
             "high_c": int(w["maxtempC"]), "low_c": int(w["mintempC"]),
             "sunrise": w["astronomy"][0]["sunrise"], "sunset": w["astronomy"][0]["sunset"]} for w in data["weather"]]
    return {"now": {"temp_c": float(cur["temp_C"]), "humidity": cur["humidity"] + "%"}, "days": days, "source": "wttr.in"}


def forecast():
    with _lock:
        if _cache["value"] and time.time() - _cache["at"] < 1800:
            return _cache["value"]
    value = None
    for url, parse in zip(FEEDS, (_itboy, _wttr)):
        try:
            response = requests.get(url, timeout=(3, 5), headers={"User-Agent": "saig-receptionist"})
            response.raise_for_status()
            value = parse(response.json())
            break
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
            continue
    if value:
        with _lock:
            _cache.update(at=time.time(), value=value)
    return value
