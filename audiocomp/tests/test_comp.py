"""压缩器规格测试：解析增益曲线、拐点连续性、指数平滑、性能与报错分类。"""

import math
import threading
import time

import pytest

import audiocomp
from audiocomp import Comp


def _analytic_gain(x, threshold, ratio, knee):
    """软拐点压缩器静态增益的解析公式（独立参考实现）。"""
    c = 1.0 / ratio - 1.0
    lo = threshold - knee / 2.0
    hi = threshold + knee / 2.0
    if x <= lo:
        return 0.0
    if x >= hi:
        return c * (x - threshold)
    d = x - lo
    return c * d * d / (2.0 * knee)


def test_comp_gain_curve_matches_analytic():
    """增益曲线与解析公式一致，误差 <= 1e-9。"""
    params = [(0.5, 4.0, 0.1), (0.3, 2.5, 0.2), (1.0, 10.0, 0.0), (0.8, 1.5, 0.5)]
    for threshold, ratio, knee in params:
        c = Comp(threshold, ratio, knee, 0.005, 0.05)
        for i in range(4001):
            x = i * 0.0005
            err = abs(c.gain_db(x) - _analytic_gain(x, threshold, ratio, knee))
            assert err <= 1e-9, (threshold, ratio, knee, x, err)


def test_comp_knee_first_order_continuous():
    """软拐点两端函数值与一阶导数均连续。"""
    c = Comp(0.5, 4.0, 0.1, 0.005, 0.05)
    for edge in (0.45, 0.55):
        h = 1e-6
        # 函数值连续
        assert abs(c.gain_db(edge - h) - c.gain_db(edge + h)) < 1e-5
        # 一阶导数连续（数值微分误差量级为 h）
        d_left = (c.gain_db(edge) - c.gain_db(edge - h)) / h
        d_right = (c.gain_db(edge + h) - c.gain_db(edge)) / h
        assert abs(d_left - d_right) < 1e-4


def test_comp_cross_buffer_continuous():
    """attack/release 平滑状态跨缓冲连续：分段处理与整体处理逐位一致。"""
    sig = [math.sin(i * 0.013) * 0.9 for i in range(20000)]
    whole = Comp(0.5, 4.0, 0.1, 0.005, 0.05).process(sig)
    c = Comp(0.5, 4.0, 0.1, 0.005, 0.05)
    chunked = c.process(sig[:7777]) + c.process(sig[7777:])
    assert chunked == whole


def test_comp_exponential_smoothing_converges():
    """常量输入下输出指数收敛到静态曲线给出的稳态增益。"""
    c = Comp(0.5, 4.0, 0.1, 0.005, 0.05)
    out = c.process([1.0] * 100000)
    steady = 0.5 + 0.5 / 4.0  # O(1.0) = T + (L - T) / R
    assert abs(out[-1] - steady) < 1e-3
    # 起控段单调下降（指数平滑，无振荡）
    head = out[:500]
    assert all(head[i + 1] <= head[i] + 1e-12 for i in range(len(head) - 1))


def test_comp_no_click():
    """阶跃输入不产生爆音：相邻采样跳变有界。"""
    c = Comp(0.5, 4.0, 0.1, 0.005, 0.05)
    sig = [0.0, 1.0, 0.0, -1.0, 0.0] * 200
    out = c.process(sig)
    assert max(abs(out[i + 1] - out[i]) for i in range(len(out) - 1)) < 1.0


def test_comp_performance_1m_samples():
    """100 万采样处理不超过 400 ms。"""
    c = Comp(0.5, 4.0, 0.1, 0.005, 0.05)
    sig = [((i * 2654435761) % 2000 - 1000) / 1000.0 for i in range(1_000_000)]
    t0 = time.perf_counter()
    out = c.process(sig)
    elapsed = time.perf_counter() - t0
    assert len(out) == 1_000_000
    assert elapsed < 0.4, f"{elapsed * 1000:.0f} ms >= 400 ms"


def test_comp_invalid_params_distinguishable():
    """非法参数可区分报错：类型错误 TypeError，取值/非有限 ValueError。"""
    with pytest.raises(ValueError):
        Comp(0.5, 0.5, 0.1, 0.005, 0.05)      # ratio < 1
    with pytest.raises(ValueError):
        Comp(0.5, 4.0, 0.1, 0.0, 0.05)        # attack <= 0
    with pytest.raises(ValueError):
        Comp(0.5, 4.0, 0.1, 0.005, -0.1)      # release <= 0
    with pytest.raises(ValueError):
        Comp(0.5, 4.0, -0.1, 0.005, 0.05)     # knee < 0
    with pytest.raises(ValueError):
        Comp(-0.5, 4.0, 0.1, 0.005, 0.05)     # threshold <= 0
    with pytest.raises(ValueError):
        Comp(float("nan"), 4.0, 0.1, 0.005, 0.05)   # 非有限
    with pytest.raises(ValueError):
        Comp(0.5, 4.0, 0.1, float("inf"), 0.05)     # 非有限
    with pytest.raises(TypeError):
        Comp("0.5", 4.0, 0.1, 0.005, 0.05)    # 非数值
    with pytest.raises(TypeError):
        Comp(0.5, 4.0, 0.1, None, 0.05)       # 非数值


def test_comp_nonfinite_input_classified():
    """非有限输入分类报错。"""
    c = Comp(0.5, 4.0, 0.1, 0.005, 0.05)
    with pytest.raises(ValueError):
        c.gain_db(float("nan"))
    with pytest.raises(ValueError):
        c.gain_db(float("inf"))
    with pytest.raises(TypeError):
        c.gain_db("loud")
    with pytest.raises(ValueError):
        c.process([0.1, float("nan"), 0.2])
    with pytest.raises(ValueError):
        c.process([0.1, float("-inf"), 0.2])
    with pytest.raises(TypeError):
        c.process([0.1, "x", 0.2])
    with pytest.raises(TypeError):
        c.process(None)


def test_comp_process_basics():
    c = Comp(0.5, 4.0, 0.1, 0.005, 0.05)
    assert c.process([]) == []
    out = c.process([0.1, 0.2, 0.9])
    assert len(out) == 3
    assert all(isinstance(v, float) for v in out)
    assert all(abs(v) <= 1.0 for v in c.process([1.0] * 100))
    assert isinstance(c.gain_db(0.8), float)


def test_comp_thread_safety():
    """并发安全：多线程共用实例不崩溃，独立实例结果与串行一致。"""
    sig = [math.sin(i * 0.017) for i in range(4000)]
    expected = Comp(0.5, 4.0, 0.1, 0.005, 0.05).process(sig)

    results = [None] * 4

    def worker(k):
        results[k] = Comp(0.5, 4.0, 0.1, 0.005, 0.05).process(sig)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r == expected for r in results)

    shared = Comp(0.5, 4.0, 0.1, 0.005, 0.05)
    errors = []

    def hammer():
        try:
            for _ in range(20):
                shared.process(sig[:100])
        except Exception as e:  # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=hammer) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
