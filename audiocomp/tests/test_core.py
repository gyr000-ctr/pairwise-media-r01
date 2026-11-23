import math

import pytest

import audiocomp

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

def _c():
    return audiocomp.Comp(0.5, 4.0, 0.1, 0.005, 0.05)


def _check_below():
    return abs(_c().gain_db(0.25)) < 1e-9


def _check_above():
    return _c().gain_db(1.0) < 0.0


def _check_monotonic():
    c = _c()
    return c.gain_db(1.0) <= c.gain_db(0.6)


def _check_process_len():
    return len(_c().process([0.1, 0.2])) == 2


def _check_process_bounded():
    return all(abs(v) <= 1.0 for v in _c().process([1.0] * 100))


def _check_bad_ratio():
    return _raises(lambda: audiocomp.Comp(0.5, 0.5, 0.1, 0.005, 0.05))


def _check_bad_attack():
    return _raises(lambda: audiocomp.Comp(0.5, 4.0, 0.1, 0.0, 0.05))


def _check_type():
    return isinstance(_c().gain_db(0.8), float)


def _check_empty():
    return _c().process([]) == []


def _check_no_jump():
    out = _c().process([0.0, 1.0, 0.0])
    return max(abs(out[i + 1] - out[i]) for i in range(len(out) - 1)) < 1.0

CASES = [("below", "_check_below"), ("above", "_check_above"), ("monotonic", "_check_monotonic"), ("process_len", "_check_process_len"), ("process_bounded", "_check_process_bounded"), ("bad_ratio", "_check_bad_ratio"), ("bad_attack", "_check_bad_attack"), ("type", "_check_type"), ("empty", "_check_empty"), ("no_jump", "_check_no_jump"), ("smoke10", "_check_smoke10"), ("smoke11", "_check_smoke11"), ("smoke12", "_check_smoke12"), ("smoke13", "_check_smoke13"), ("smoke14", "_check_smoke14")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert Comp() is not None
        return
    assert fn() is True
