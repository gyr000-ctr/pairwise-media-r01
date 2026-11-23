"""audiocomp 核心 API：软拐点压缩器。

静态增益曲线（解析公式，一阶连续）::

    输入电平 x，阈值 T，拐点宽度 W，压缩比 R，斜率 c = 1/R - 1

    x <= T - W/2:            gain = 0
    T - W/2 < x < T + W/2:   gain = c * (x - T + W/2)^2 / (2W)
    x >= T + W/2:            gain = c * (x - T)

process 在线性域工作：电平 L = |x|，目标增益因子 G = O(L) / L，
其中 O(L) = L + gain_db(L)。增益因子用 attack/release 指数平滑，
平滑状态跨 process 调用保持连续。
"""

from __future__ import annotations

import math
import threading

__all__ = ["Comp"]


def _check_number(name, value):
    """区分报错：非数值 -> TypeError；非有限 -> ValueError。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{name} must be a real number, got {type(value).__name__}"
        )
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


class Comp:
    """软拐点压缩器。

    参数（均为有限实数）：
        threshold   阈值，必须 > 0
        ratio       压缩比，必须 >= 1
        knee        拐点宽度，必须 >= 0（0 为硬拐点）
        attack      起控时间常数（秒），必须 > 0
        release     释放时间常数（秒），必须 > 0
        sample_rate 采样率（Hz），必须 > 0，默认 48000
    """

    def __init__(self, threshold=0.5, ratio=4.0, knee=0.1,
                 attack=0.005, release=0.05, sample_rate=48000.0):
        threshold = _check_number("threshold", threshold)
        ratio = _check_number("ratio", ratio)
        knee = _check_number("knee", knee)
        attack = _check_number("attack", attack)
        release = _check_number("release", release)
        sample_rate = _check_number("sample_rate", sample_rate)
        if threshold <= 0.0:
            raise ValueError(f"threshold must be > 0, got {threshold!r}")
        if ratio < 1.0:
            raise ValueError(f"ratio must be >= 1, got {ratio!r}")
        if knee < 0.0:
            raise ValueError(f"knee must be >= 0, got {knee!r}")
        if attack <= 0.0:
            raise ValueError(f"attack must be > 0, got {attack!r}")
        if release <= 0.0:
            raise ValueError(f"release must be > 0, got {release!r}")
        if sample_rate <= 0.0:
            raise ValueError(f"sample_rate must be > 0, got {sample_rate!r}")

        self.threshold = threshold
        self.ratio = ratio
        self.knee = knee
        self.attack = attack
        self.release = release
        self.sample_rate = sample_rate

        # 静态曲线预计算
        self._t = threshold
        self._inv_r = 1.0 / ratio
        self._c = self._inv_r - 1.0          # 1/R - 1
        half = 0.5 * knee
        self._lo = threshold - half          # 拐点下沿
        self._hi = threshold + half          # 拐点上沿
        # 拐点区系数：gain = c * (x - lo)^2 / (2W) = ck2 * (x - lo)^2
        self._ck2 = self._c / (2.0 * knee) if knee > 0.0 else 0.0
        self._inv_2w = 1.0 / (2.0 * knee) if knee > 0.0 else 0.0

        # 指数平滑系数：y[n] = a*y[n-1] + (1-a)*target，a = exp(-1/(tau*fs))
        self._a_attack = math.exp(-1.0 / (attack * sample_rate))
        self._b_attack = 1.0 - self._a_attack
        self._a_release = math.exp(-1.0 / (release * sample_rate))
        self._b_release = 1.0 - self._a_release

        self._gain = 1.0                     # 平滑后的线性增益因子状态
        self._lock = threading.Lock()

    def gain_db(self, level_db):
        """静态增益曲线：返回 O(level) - level（解析公式，一阶连续）。"""
        x = _check_number("level_db", level_db)
        lo = self._lo
        if x <= lo:
            return 0.0
        if x >= self._hi:
            return float(self._c * (x - self._t))
        d = x - lo
        return float(self._c * d * d * self._inv_2w)

    def process(self, samples):
        """处理一串采样（有限实数），返回等长 float 列表。

        增益因子按 attack/release 指数平滑，状态跨调用连续，
        因此分段处理与一次性处理结果逐位一致。
        """
        if isinstance(samples, list):
            xs = samples
        else:
            tolist = getattr(samples, "tolist", None)
            if tolist is not None:
                xs = tolist()
            else:
                try:
                    xs = list(samples)
                except TypeError:
                    raise TypeError(
                        "samples must be an iterable of real numbers"
                    ) from None
        if not xs:
            return []
        # 非有限输入分类报错（sum 对任何 NaN/inf 都非有限；
        # 若只是有限值求和溢出则再做精确扫描，不误报）
        if not math.isfinite(sum(xs)):
            for v in xs:
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise TypeError(
                        f"samples must be real numbers, got {type(v).__name__}"
                    )
                if not math.isfinite(v):
                    raise ValueError(f"samples must be finite, got {v!r}")

        lo = self._lo
        hi = self._hi
        t = self._t
        inv_r = self._inv_r
        ck2 = self._ck2
        a_a = self._a_attack
        b_a = self._b_attack
        a_r = self._a_release
        b_r = self._b_release

        out = []
        ap = out.append
        with self._lock:
            gs = self._gain
            for x in xs:
                L = abs(x)
                if L <= lo:
                    g = 1.0
                elif L >= hi:
                    g = (t + (L - t) * inv_r) / L
                else:
                    d = L - lo
                    g = (L + ck2 * d * d) / L if L > 0.0 else 1.0
                if g < gs:
                    gs = a_a * gs + b_a * g
                else:
                    gs = a_r * gs + b_r * g
                ap(x * gs)
            self._gain = gs
        return out
