"""Resource bounds for one HTTP turn, including upstream retries."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

_budget = ContextVar("turn_budget", default=None)


class CapacityError(RuntimeError):
    pass


class TurnExpired(RuntimeError):
    pass


@contextmanager
def turn_budget(charge, seconds=120):
    token = _budget.set((charge, monotonic() + seconds))
    try:
        yield
    finally:
        _budget.reset(token)


def remaining(maximum):
    budget = _budget.get()
    if budget:
        left = budget[1] - monotonic()
        if left <= 0:
            raise TurnExpired("本轮处理超时，请拆分问题后重试。")
        return min(maximum, left)
    return maximum


def charge_attempt():
    remaining(120)
    if budget := _budget.get():
        budget[0]()
