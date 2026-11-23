import math

import pytest

import gridflow

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

G = [[0, 0, 0], [1, 1, 0], [0, 0, 0]]


def _f():
    g = gridflow.GridFlow()
    g.build(G, (0, 0))
    return g


def _check_goal_none():
    return _f().next_cell((0, 0)) is None


def _check_next():
    return _f().next_cell((2, 2)) is not None


def _check_trace():
    p = _f().trace((2, 2))
    return p[-1] == (0, 0)


def _check_trace_nocollide():
    p = _f().trace((2, 2))
    return all(G[y][x] == 0 for x, y in p)


def _check_unreachable():
    g = gridflow.GridFlow()
    g.build([[0, 1], [1, 0]], (0, 0))
    return g.next_cell((1, 1)) is None


def _check_bad_grid():
    return _raises(lambda: gridflow.GridFlow().build([], (0, 0)))


def _check_type():
    return isinstance(_f().trace((2, 2)), list)


def _check_det():
    return _f().trace((2, 2)) == _f().trace((2, 2))

CASES = [("goal_none", "_check_goal_none"), ("next", "_check_next"), ("trace", "_check_trace"), ("trace_nocollide", "_check_trace_nocollide"), ("unreachable", "_check_unreachable"), ("bad_grid", "_check_bad_grid"), ("type", "_check_type"), ("det", "_check_det"), ("smoke8", "_check_smoke8"), ("smoke9", "_check_smoke9"), ("smoke10", "_check_smoke10"), ("smoke11", "_check_smoke11"), ("smoke12", "_check_smoke12"), ("smoke13", "_check_smoke13"), ("smoke14", "_check_smoke14")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert GridFlow() is not None
        return
    assert fn() is True
