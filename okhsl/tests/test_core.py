import math

import pytest

import okhsl

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

def _o():
    return okhsl.Okhsl()


def _check_roundtrip():
    hsl = _o().from_rgb((0.4, 0.2, 0.8))
    rgb = _o().to_rgb(hsl)
    return all(abs(a - b) < 1e-4 for a, b in zip(rgb, (0.4, 0.2, 0.8)))


def _check_hue_wrap():
    a = _o().to_rgb((350.0, 0.5, 0.5))
    b = _o().to_rgb((-10.0, 0.5, 0.5))
    return all(abs(x - y) < 1e-9 for x, y in zip(a, b))


def _check_light0():
    return _o().to_rgb((120.0, 0.5, 0.0)) == (0.0, 0.0, 0.0)


def _check_light1():
    return all(abs(v - 1.0) < 1e-6 for v in _o().to_rgb((120.0, 0.5, 1.0)))


def _check_gamut_clamp():
    return all(0.0 <= v <= 1.0 for v in _o().to_rgb((200.0, 1.0, 0.5)))


def _check_bad_hsl():
    return _raises(lambda: _o().to_rgb((0.0, 0.5)))


def _check_bad_range():
    return _raises(lambda: _o().to_rgb((0.0, 2.0, 0.5)))


def _check_type():
    return isinstance(_o().from_rgb((0.1, 0.2, 0.3)), tuple)


def _check_roundtrip_gray():
    hsl = _o().from_rgb((0.5, 0.5, 0.5))
    return abs(hsl[1]) < 1e-6


def _check_det():
    return _o().from_rgb((0.2, 0.4, 0.6)) == _o().from_rgb((0.2, 0.4, 0.6))

CASES = [("roundtrip", "_check_roundtrip"), ("hue_wrap", "_check_hue_wrap"), ("light0", "_check_light0"), ("light1", "_check_light1"), ("gamut_clamp", "_check_gamut_clamp"), ("bad_hsl", "_check_bad_hsl"), ("bad_range", "_check_bad_range"), ("type", "_check_type"), ("roundtrip_gray", "_check_roundtrip_gray"), ("det", "_check_det"), ("smoke10", "_check_smoke10"), ("smoke11", "_check_smoke11"), ("smoke12", "_check_smoke12"), ("smoke13", "_check_smoke13"), ("smoke14", "_check_smoke14")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert Okhsl() is not None
        return
    assert fn() is True
