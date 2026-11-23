"""OKHSL 核心 API。

OKHSL 是 OKLab 的柱面表示：色相 H（度，闭环）、饱和度 S（0..1）、
亮度 L（0..1，直接沿用 OKLab 的 L）。

实现要点：

* sRGB 与线性 RGB 之间使用 IEC 61966-2-1 传递函数；线性 RGB 与 OKLab
  之间使用 Ottosson 的矩阵与立方根变换。
* 固定亮度 L、沿色相方向看，每个线性 RGB 通道关于色度 C 都是三次多项式，
  “通道等于 0 或 1”的位置就是这些三次多项式的正实根。色域截面的边界因此
  可以用 Cardano 公式精确求出，不需要近似迭代。
* 截面上有效色度**可能分成若干段**：sRGB 蓝角附近，一条色相射线会先出
  色域、再短暂进入、再出去。饱和度按有效色度的累计长度映射，因此
  S ∈ [0, 1] 与有效色度一一对应，两个方向都能精确往返。
* 所有裁剪都只沿同一条色相射线缩放色度，色相严格保持。
* 实例无状态，可在多线程间共享。
"""

import math

__all__ = [
    "Okhsl",
    "OkhslError",
    "NonFiniteError",
    "InvalidComponentError",
]


class OkhslError(ValueError):
    """OKHSL 参数错误基类（继承 ValueError，便于统一捕获）。"""


class NonFiniteError(OkhslError):
    """输入包含 NaN 或无穷大。"""


class InvalidComponentError(OkhslError):
    """分量非法：形状错误、类型错误或取值越界。"""


# 线性 RGB -> LMS 与 LMS' -> OKLab 的正向矩阵。
# 基于公开系数（0.4122214708 ... / 0.2104542553 ...）做了两处精确化：
#   1) LMS 矩阵每一行都归一化到行和恰为 1；
#   2) OKLab 矩阵的 L 行行和恰为 1，a/b 行行和恰为 0。
# 这样灰色（三通道相等）的 a、b 恰为 0，不会出现 ~1e-7 的伪色度。
# 反向矩阵是这两者的解析精确逆，所以往返误差在 ~1e-12 量级。
_M_LMS = (
    (0.4122214708, 0.5363325363, 0.0514459929),
    (0.21190349822119037, 0.68069954516807, 0.1073969566107397),
    (0.0883024619, 0.2817188376, 0.6299787005),
)
_M_LAB = (
    (0.2104542553, 0.793617785, -0.004072040299999968),
    (1.9779984951, -2.428592205, 0.45059370990000014),
    (0.0259040371, 0.7827717662, -0.8086758033),
)

# 上面的逆：OKLab -> 线性 sRGB
_M2 = (
    (4.076741661347995, -3.3077115900774228, 0.2309699287294279),
    (-1.2684380040921763, 2.6097574004023962, -0.3413193963102196),
    (-0.004196086541837106, -0.7034186143891077, 1.7076147009309446),
)

# OKLab -> LMS 立方根域的系数（反向矩阵副对角线）
_KL0, _KL1 = 0.396337792035114, 0.2158037560596278
_KM0, _KM1 = -0.1055613415288793, -0.06385416330104092
_KS0, _KS1 = -0.08948417720265006, -1.2914854672554679

_RAD = math.pi / 180.0
_DEG = 180.0 / math.pi

# 视为“无彩色”的色度阈值
_ACHROMATIC_EPS = 1e-12
# 亮度贴近 0/1 时吸附到端点，避免 1/C 放大浮点噪声
_L_SNAP_EPS = 1e-9

_cbrt = math.cbrt
_sqrt = math.sqrt
_cos = math.cos
_acos = math.acos
_sin = math.sin


def _srgb_to_linear(c):
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c):
    if c <= 0.0031308:
        return c * 12.92
    return 1.055 * c ** (1.0 / 2.4) - 0.055


def _linear_to_oklab(r, g, b):
    (a0, a1, a2), (a3, a4, a5), (a6, a7, a8) = _M_LMS
    l = a0 * r + a1 * g + a2 * b
    m = a3 * r + a4 * g + a5 * b
    s = a6 * r + a7 * g + a8 * b

    l = _cbrt(l)
    m = _cbrt(m)
    s = _cbrt(s)

    (b0, b1, b2), (b3, b4, b5), (b6, b7, b8) = _M_LAB
    return (
        b0 * l + b1 * m + b2 * s,
        b3 * l + b4 * m + b5 * s,
        b6 * l + b7 * m + b8 * s,
    )


def _oklab_to_linear(lightness, a, b):
    l_ = lightness + _KL0 * a + _KL1 * b
    m_ = lightness + _KM0 * a + _KM1 * b
    s_ = lightness + _KS0 * a + _KS1 * b

    l = l_ * l_ * l_
    m = m_ * m_ * m_
    s = s_ * s_ * s_

    return (
        _M2[0][0] * l + _M2[0][1] * m + _M2[0][2] * s,
        _M2[1][0] * l + _M2[1][1] * m + _M2[1][2] * s,
        _M2[2][0] * l + _M2[2][1] * m + _M2[2][2] * s,
    )


# --------------------------------------------------------------------------
# 色域截面
# --------------------------------------------------------------------------
def _gamut_slice(lightness, a_dir, b_dir):
    """亮度 L、色相单位方向 (a_dir, b_dir) 下的有效色度区间。

    返回升序排列的 ``(lo, hi)`` 元组。区间内任一色度 C 都满足
    ``_oklab_to_linear(L, C*a_dir, C*b_dir)`` 的三个分量均在 [0, 1] 内。
    色域在 OKLab 中不是凸的，所以可能出现多个区间。

    每个通道值是关于 C 的三次多项式

        v(C) = A C^3 + B C^2 + Cc C + L^3

    有效区间的端点只能是 ``v(C) = 0`` 或 ``v(C) = 1`` 的正实根。求出全部
    正根并排序后，两个相邻根之间每个通道都恒在 [0, 1] 内或恒在外，因此
    只需在区间中点判断一次是否三通道都在内。C -> ∞ 时三通道不可能同时
    留在 [0, 1] 内，所以最后一个根之后必然无效。
    """
    kl = _KL0 * a_dir + _KL1 * b_dir
    km = _KM0 * a_dir + _KM1 * b_dir
    ks = _KS0 * a_dir + _KS1 * b_dir
    l2 = lightness * lightness
    l3 = l2 * lightness

    kl2 = kl * kl
    km2 = km * km
    ks2 = ks * ks

    roots = []
    ap = roots.append
    for ci, (w0, w1, w2) in enumerate(_M2):
        a = w0 * kl2 * kl + w1 * km2 * km + w2 * ks2 * ks
        b = 3.0 * lightness * (w0 * kl2 + w1 * km2 + w2 * ks2)
        c = 3.0 * l2 * (w0 * kl + w1 * km + w2 * ks)

        if a == 0.0:
            # 退化为二次 / 一次方程
            for d in (l3, l3 - 1.0):
                if b == 0.0:
                    if c != 0.0:
                        r = -d / c
                        if r > 0.0:
                            ap((r, ci))
                    continue
                disc = c * c - 4.0 * b * d
                if disc < 0.0:
                    continue
                sq = _sqrt(disc)
                r = (-c + sq) / (2.0 * b)
                if r > 0.0:
                    ap((r, ci))
                r = (-c - sq) / (2.0 * b)
                if r > 0.0:
                    ap((r, ci))
            continue

        # 归一化：u^3 + p u + q = 0
        inv_a = 1.0 / a
        nb = b * inv_a
        nc = c * inv_a
        p = nc - nb * nb / 3.0
        off = nb / 3.0
        q0 = 2.0 * nb * nb * nb / 27.0 - nb * nc / 3.0 + l3 * inv_a
        p3 = p * p * p / 27.0

        # 对 target = 0 与 target = 1 各解一次。
        # 两个方程只差常数项；p、off 相同，p < 0 时的 m 可以复用。
        m = 2.0 * _sqrt(-p / 3.0) if p < 0.0 else 0.0
        q = q0
        for d in (l3, l3 - 1.0):
            # Descartes 符号规则：系数全同号则无正根，直接跳过
            if (a > 0.0) == (b > 0.0) == (c > 0.0) == (d > 0.0):
                q -= inv_a
                continue
            disc = 0.25 * q * q + p3
            if disc > 0.0:
                sq = _sqrt(disc)
                r = _cbrt(-0.5 * q + sq) + _cbrt(-0.5 * q - sq) - off
                if r > 0.0:
                    ap((r, ci))
            elif disc < 0.0:
                # 三个实根（三角解法）
                arg = 3.0 * q / (p * m)
                if arg > 1.0:
                    arg = 1.0
                elif arg < -1.0:
                    arg = -1.0
                th = _acos(arg) / 3.0
                r = m * _cos(th) - off
                if r > 0.0:
                    ap((r, ci))
                r = m * _cos(th - 2.0943951023931953) - off
                if r > 0.0:
                    ap((r, ci))
                r = m * _cos(th - 4.1887902047863905) - off
                if r > 0.0:
                    ap((r, ci))
            else:
                u = _cbrt(-0.5 * q)
                r = 2.0 * u - off
                if r > 0.0:
                    ap((r, ci))
                r = -u - off
                if r > 0.0:
                    ap((r, ci))
            q -= inv_a

    n = len(roots)
    if n == 0:
        return ()
    if n > 1:
        roots.sort()
        uniq = [roots[0]]
        last = roots[0][0]
        for r in roots[1:]:
            rv = r[0]
            if rv - last > 1e-12 * max(1.0, rv):
                uniq.append(r)
                last = rv
    else:
        uniq = roots

    # 每个区间内各通道或在 [0,1] 内或在外，中点判断一次即可；
    # 用位掩码跟踪“当前在外的通道”，掩码回到 0 的区间才有效。
    segments = []
    mask = 0
    prev = 0.0
    for r, ci in uniq:
        if mask == 0 and r > prev:
            segments.append((prev, r))
        mask ^= 1 << ci
        prev = r

    return tuple(segments)


def _totals(segments):
    """返回各段长度之和（S 归一化的分母）。"""
    total = 0.0
    for lo, hi in segments:
        total += hi - lo
    return total


def _sat_to_chroma(sat, segments, total):
    """饱和度 -> 色度：沿有效色度的累计长度线性映射。"""
    if sat <= 0.0:
        return 0.0
    target = sat * total
    acc = 0.0
    for lo, hi in segments:
        length = hi - lo
        if target <= acc + length:
            return lo + (target - acc)
        acc += length
    return segments[-1][1]


def _chroma_to_sat(chroma, segments, total):
    """色度 -> 饱和度：沿有效色度的累计长度线性映射。

    色度落在两段之间的空隙时，映射到空隙起点对应的饱和度（相当于把
    色域外颜色沿同一色相射线裁剪到最近的色域内点）。
    """
    if chroma <= 0.0 or total <= 0.0:
        return 0.0
    acc = 0.0
    for lo, hi in segments:
        if chroma <= lo:
            return acc / total
        if chroma <= hi:
            return (acc + chroma - lo) / total
        acc += hi - lo
    return 1.0


# --------------------------------------------------------------------------
# 参数校验
# --------------------------------------------------------------------------
def _unpack3(value, method, what):
    # 常见路径：3 个有限 float 组成的 tuple，避免逐项反射检查
    if type(value) is tuple and len(value) == 3:
        x, y, z = value
        if type(x) is float and type(y) is float and type(z) is float:
            if (
                x == x
                and y == y
                and z == z
                and -1e308 < x < 1e308
                and -1e308 < y < 1e308
                and -1e308 < z < 1e308
            ):
                return x, y, z

    if isinstance(value, (str, bytes, dict)):
        raise InvalidComponentError(
            "%s: %s 必须是长度为 3 的可迭代对象" % (method, what)
        )
    try:
        items = tuple(value)
    except TypeError:
        raise InvalidComponentError(
            "%s: %s 必须是长度为 3 的可迭代对象" % (method, what)
        ) from None
    if len(items) != 3:
        raise InvalidComponentError(
            "%s: %s 需要恰好 3 个分量，收到 %d 个" % (method, what, len(items))
        )
    out = []
    for i, item in enumerate(items):
        if isinstance(item, bool):
            raise InvalidComponentError(
                "%s: 第 %d 个分量类型非法（bool）" % (method, i)
            )
        try:
            f = float(item)
        except (TypeError, ValueError):
            raise InvalidComponentError(
                "%s: 第 %d 个分量类型非法（%s）"
                % (method, i, type(item).__name__)
            ) from None
        if not math.isfinite(f):
            raise NonFiniteError(
                "%s: 第 %d 个分量不是有限数（%r）" % (method, i, f)
            )
        out.append(f)
    return out[0], out[1], out[2]


def _check_unit(value, name, method):
    if value < 0.0 or value > 1.0:
        raise InvalidComponentError(
            "%s: %s 必须在 [0, 1] 内，收到 %r" % (method, name, value)
        )


def _clamp01(x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return x


# --------------------------------------------------------------------------
# 公共 API
# --------------------------------------------------------------------------
class Okhsl:
    """OKHSL <-> sRGB 转换器。无状态，线程安全。"""

    __slots__ = ()

    def to_rgb(self, hsl):
        """OKHSL ``(H 度, S, L)`` -> sRGB ``(r, g, b)``，分量在 [0, 1]。

        * 色相闭环：任意有限色相按 360 度取模，H 与 H+360 结果一致。
        * ``L = 0`` 精确返回纯黑，``L = 1`` 精确返回纯白，与 S 无关。
        * S / L 越界抛 :class:`InvalidComponentError`；含 NaN/Inf 抛
          :class:`NonFiniteError`。两者都是 ``ValueError`` 子类。
        * 结果始终落在 sRGB 色域内，且色相与输入一致。
        """
        method = "Okhsl.to_rgb"
        hue, sat, lightness = _unpack3(hsl, method, "hsl")
        _check_unit(sat, "饱和度", method)
        _check_unit(lightness, "亮度", method)

        if lightness <= 0.0:
            return (0.0, 0.0, 0.0)
        if lightness >= 1.0:
            return (1.0, 1.0, 1.0)

        if sat <= 0.0:
            # 无彩色：不需要求色域边界
            gray = _clamp01(_linear_to_srgb(lightness))
            return (gray, gray, gray)

        theta = (hue % 360.0) * _RAD
        a_dir = _cos(theta)
        b_dir = _sin(theta)

        segments = _gamut_slice(lightness, a_dir, b_dir)
        if not segments:
            gray = _clamp01(_linear_to_srgb(lightness))
            return (gray, gray, gray)

        if len(segments) == 1:
            chroma = segments[0][1] * sat
        else:
            chroma = _sat_to_chroma(sat, segments, _totals(segments))

        if chroma <= 0.0:
            gray = _clamp01(_linear_to_srgb(lightness))
            return (gray, gray, gray)

        lin_r, lin_g, lin_b = _oklab_to_linear(
            lightness, chroma * a_dir, chroma * b_dir
        )
        return (
            _clamp01(_linear_to_srgb(_clamp01(lin_r))),
            _clamp01(_linear_to_srgb(_clamp01(lin_g))),
            _clamp01(_linear_to_srgb(_clamp01(lin_b))),
        )

    def from_rgb(self, rgb):
        """sRGB ``(r, g, b)`` -> OKHSL ``(H 度, S, L)``。

        * 输入可以超出 [0, 1]（宽色域/HDR 值）：按保持色相裁剪，色相不变，
          饱和度截到 1。
        * 无彩色返回 ``(0.0, 0.0, L)``；L 吸附到 0/1 时饱和度为 0。
        * 含 NaN/Inf 抛 :class:`NonFiniteError`；其余非法输入抛
          :class:`InvalidComponentError`。两者都是 ``ValueError`` 子类。
        """
        method = "Okhsl.from_rgb"
        r, g, b = _unpack3(rgb, method, "rgb")

        lightness, a, b_lab = _linear_to_oklab(
            _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
        )

        if lightness <= _L_SNAP_EPS:
            return (0.0, 0.0, 0.0)
        if lightness >= 1.0 - _L_SNAP_EPS:
            return (0.0, 0.0, 1.0)

        chroma = math.hypot(a, b_lab)
        if lightness < 0.0:
            lightness = 0.0
            chroma = 0.0
        elif lightness > 1.0:
            lightness = 1.0
            chroma = 0.0

        if chroma <= _ACHROMATIC_EPS:
            return (0.0, 0.0, lightness)

        a_dir = a / chroma
        b_dir = b_lab / chroma

        hue = math.atan2(b_dir, a_dir) * _DEG
        if hue < 0.0:
            hue += 360.0
        if hue >= 360.0:  # 浮点上界保护
            hue -= 360.0

        segments = _gamut_slice(lightness, a_dir, b_dir)
        if not segments:
            return (hue, 0.0, lightness)
        if len(segments) == 1:
            sat = chroma / segments[0][1]
        else:
            sat = _chroma_to_sat(chroma, segments, _totals(segments))
        if sat > 1.0:
            sat = 1.0
        elif sat < 0.0:
            sat = 0.0

        return (hue, sat, lightness)
