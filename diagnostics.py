"""Optional per-request timing events. Do not record prompts, URLs or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

_current=ContextVar("saig_events",default=None)

@contextmanager
def capture(enabled):
    events=[]
    token=_current.set((perf_counter(),events) if enabled else None)
    try:
        yield events
    finally:
        _current.reset(token)

@contextmanager
def timed(stage):
    trace=_current.get()
    if trace is None:
        yield {}
        return
    epoch,events=trace
    start=perf_counter()
    event={"stage":stage,"at_ms":round((start-epoch)*1000,1)}
    events.append(event)
    try:
        yield event
    except Exception as exc:
        event["error"]=type(exc).__name__
        raise
    finally:
        event["ms"]=round((perf_counter()-start)*1000,1)
