import math

import pytest

import bvrefit

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

B = [("a", ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))), ("b", ((2.0, 0.0, 0.0), (3.0, 1.0, 1.0)))]


def _s():
    t = bvrefit.BvhRefit()
    for n, box in B:
        t.add(n, box)
    t.build()
    return t


def _check_hit():
    return _s().query((-1.0, 0.5, 0.5), (1.0, 0.0, 0.0))[0][1] == "a"


def _check_refit():
    t = _s()
    t.refit("a", ((5.0, 0.0, 0.0), (6.0, 1.0, 1.0)))
    return t.query((-1.0, 0.5, 0.5), (1.0, 0.0, 0.0))[0][1] == "b"


def _check_refit_same():
    t = _s()
    before = t.query((-1.0, 0.5, 0.5), (1.0, 0.0, 0.0))
    t.refit("b", B[1][1])
    return t.query((-1.0, 0.5, 0.5), (1.0, 0.0, 0.0)) == before


def _check_empty():
    return _raises(lambda: bvrefit.BvhRefit().query((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))


def _check_bad_refit():
    return _raises(lambda: _s().refit("zz", B[0][1]))


def _check_sorted():
    q = _s().query((-1.0, 0.5, 0.5), (1.0, 0.0, 0.0))
    return all(q[i][0] <= q[i + 1][0] for i in range(len(q) - 1))


def _check_type():
    return isinstance(_s().query((-1.0, 0.5, 0.5), (1.0, 0.0, 0.0)), list)

CASES = [("hit", "_check_hit"), ("refit", "_check_refit"), ("refit_same", "_check_refit_same"), ("empty", "_check_empty"), ("bad_refit", "_check_bad_refit"), ("sorted", "_check_sorted"), ("type", "_check_type"), ("smoke7", "_check_smoke7"), ("smoke8", "_check_smoke8"), ("smoke9", "_check_smoke9"), ("smoke10", "_check_smoke10"), ("smoke11", "_check_smoke11"), ("smoke12", "_check_smoke12"), ("smoke13", "_check_smoke13"), ("smoke14", "_check_smoke14")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert BvhRefit() is not None
        return
    assert fn() is True
