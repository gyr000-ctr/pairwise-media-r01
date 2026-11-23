import math

import pytest

import tangent

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

P = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]


def _t():
    return tangent.Tangent()


def _check_unit():
    v = _t().at(P, 0.5)
    return abs(math.hypot(v[0], v[1]) - 1.0) < 1e-6


def _check_normal_orth():
    t = _t()
    a = t.at(P, 0.4)
    b = t.normal(P, 0.4)
    return abs(a[0] * b[0] + a[1] * b[1]) < 1e-6


def _check_bad_points():
    return _raises(lambda: _t().at([(0.0, 0.0)], 0.5))


def _check_bad_t():
    return _raises(lambda: _t().at(P, 1.5))


def _check_arclen_len():
    return len(_t().arclen_param(P, 10)) == 10


def _check_arclen_speed():
    pts = _t().arclen_param(P, 20)
    speeds = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    return max(speeds) - min(speeds) < 1e-2


def _check_type():
    return isinstance(_t().at(P, 0.2), tuple)


def _check_det():
    return _t().at(P, 0.3) == _t().at(P, 0.3)

CASES = [("unit", "_check_unit"), ("normal_orth", "_check_normal_orth"), ("bad_points", "_check_bad_points"), ("bad_t", "_check_bad_t"), ("arclen_len", "_check_arclen_len"), ("arclen_speed", "_check_arclen_speed"), ("type", "_check_type"), ("det", "_check_det"), ("smoke8", "_check_smoke8"), ("smoke9", "_check_smoke9"), ("smoke10", "_check_smoke10"), ("smoke11", "_check_smoke11"), ("smoke12", "_check_smoke12"), ("smoke13", "_check_smoke13"), ("smoke14", "_check_smoke14")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert Tangent() is not None
        return
    assert fn() is True
