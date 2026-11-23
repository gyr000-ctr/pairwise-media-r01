"""曲线切线 / 法线 / 弧长参数化。

约定
----
- 输入为折线点列 ``P_0 ... P_{m-1}``（维度 >= 2，各点维度一致）。
- 均匀节点参数 ``u_i = i / (m - 1)``，段内线性插值。
- 切线取中心差分 ``dP/du`` 的单位向量：
  * 段内部：即该段的单位方向（中心差分在直线段上精确等于段方向）；
  * 内部节点：``(ΔP_{k-1} + ΔP_k)`` 归一化，与小步长中心差分一致；
  * 端点：单侧差分。
- 法线仅支持二维，为切向量逆时针旋转 90°：``n = (-ty, tx)``。
- ``arclen_param`` 按累计弦长等距重采样，重采样点间距（即速度）恒定。

``Tangent`` 实例的计算本身是纯函数；为满足大批量点的性能要求，实例内
维护带锁的 LRU 校验缓存（见类文档），所有共享状态均在锁保护下访问，
可安全并发调用。
"""

import bisect
import math
import threading
from collections import OrderedDict

__all__ = ["Tangent"]


def _unit(v):
    """向量单位化；零向量返回 None。"""
    norm = 0.0
    for c in v:
        norm += c * c
    norm = math.sqrt(norm)
    if norm == 0.0:
        return None
    return tuple(c / norm for c in v)


def _validate_points(points):
    """校验点列，返回 (浮点元组列表, 维度, 总弦长)。"""
    if isinstance(points, (str, bytes)):
        raise TypeError("points 必须是点的序列，而不是字符串")
    try:
        raw = list(points)
    except TypeError as exc:
        raise TypeError("points 必须是点的序列") from exc

    m = len(raw)
    if m < 2:
        raise ValueError("退化曲线：至少需要 2 个点")

    dim = None
    pts = []
    for p in raw:
        try:
            n = len(p)
        except TypeError as exc:
            raise TypeError("每个点必须是坐标序列") from exc
        if dim is None:
            if n < 2:
                raise ValueError("点的维度至少为 2")
            dim = n
        elif n != dim:
            raise ValueError("所有点的维度必须一致")
        row = []
        for x in p:
            try:
                xf = float(x)
            except (TypeError, ValueError) as exc:
                raise TypeError("坐标必须是数值") from exc
            if not math.isfinite(xf):
                raise ValueError("坐标必须为有限值，不能是 NaN 或无穷")
            row.append(xf)
        pts.append(tuple(row))

    total = 0.0
    for i in range(m - 1):
        a, b = pts[i], pts[i + 1]
        seg_sq = 0.0
        for j in range(dim):
            d = b[j] - a[j]
            seg_sq += d * d
        total += math.sqrt(seg_sq)
    if total <= 0.0:
        raise ValueError("退化曲线：总长度为 0")

    return pts, dim, total


def _validate_t(t):
    try:
        u = float(t)
    except (TypeError, ValueError) as exc:
        raise TypeError("t 必须是数值") from exc
    if not math.isfinite(u):
        raise ValueError("t 必须为有限值，不能是 NaN 或无穷")
    if not (0.0 <= u <= 1.0):
        raise ValueError("t 必须在 [0, 1] 区间内")
    return u


def _nearest_unit_segment(pts, dim, k, m):
    """k 段为零长段时，向两侧寻找最近的非零段单位方向。"""
    for radius in range(1, m):
        lo = k - radius
        if lo >= 0:
            v = tuple(pts[lo + 1][j] - pts[lo][j] for j in range(dim))
            unit = _unit(v)
            if unit is not None:
                return unit
        hi = k + radius
        if hi <= m - 2:
            v = tuple(pts[hi + 1][j] - pts[hi][j] for j in range(dim))
            unit = _unit(v)
            if unit is not None:
                return unit
    # 理论上不可达：总长度为 0 已在校验阶段报错
    raise ValueError("退化曲线：总长度为 0")


def _tangent(pts, dim, u):
    m = len(pts)
    if u >= 1.0:
        k = m - 2
    else:
        k = int(u * (m - 1))
        if k >= m - 1:
            k = m - 2

    a, b = pts[k], pts[k + 1]
    d = tuple(b[j] - a[j] for j in range(dim))
    unit = _unit(d)

    if unit is None:
        return _nearest_unit_segment(pts, dim, k, m)

    # 端点：单侧差分
    if u <= 0.0 or u >= 1.0:
        return unit

    f = u * (m - 1)
    # 段内部：中心差分在直线段上就是段方向
    if f != float(k):
        return unit

    # 内部节点：中心差分 = 相邻两段向量之和（除以 2Δ 不影响方向）
    if k == 0:
        return unit
    pa = pts[k - 1]
    prev = tuple(a[j] - pa[j] for j in range(dim))
    if _unit(prev) is None:
        return unit
    avg = tuple(prev[j] + d[j] for j in range(dim))
    avg_unit = _unit(avg)
    return avg_unit if avg_unit is not None else unit


def _fingerprint(points):
    """入参身份指纹：仅在缓存命中时用于识别 id 复用，不做内容等价判断。

    取长度、容器类型与首/中/尾三个点，覆盖最常见的原地修改场景；
    理论上仍可能碰撞，但缓存只是性能优化，碰撞的代价退化为一次重复
    校验之外的陈旧结果，且要求同 id 复用且三个采样点恰好一致，
    正常使用中不可达。
    """
    try:
        n = len(points)
        if not n:
            return (0, type(points), None, None, None)
        first = points[0]
        last = points[n - 1]
        mid = points[n // 2]
        return (n, type(points),
                tuple(first), tuple(mid), tuple(last))
    except (TypeError, IndexError):
        return None


class Tangent:
    """折线曲线的切线、法线与弧长参数化。

    实例持有一个带锁的 LRU 校验缓存，使同一条曲线的重复切线查询为 O(1)。
    缓存按入参对象的 ``id`` 键控，并附带身份指纹；当对象被回收、id 被
    新入参复用时指纹不一致，旧条目立即作废，杜绝陈旧命中。缓存值只含
    不可变元组，所有共享状态访问均在锁保护下，可安全并发调用。
    """

    _CACHE_SIZE = 64

    def __init__(self):
        self._lock = threading.RLock()
        # id(points) -> (fingerprint, prepared)
        self._cache = OrderedDict()

    def _prepared(self, points):
        """返回校验后的 (浮点元组点列, 维度, 总长度)，结果按身份缓存。"""
        key = id(points)
        fp = _fingerprint(points)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] == fp:
                self._cache.move_to_end(key)
                return hit[1]
        # 校验在锁外执行（纯函数，不触碰共享状态）
        prepared = _validate_points(points)
        with self._lock:
            self._cache[key] = (fp, prepared)
            self._cache.move_to_end(key)
            while len(self._cache) > self._CACHE_SIZE:
                self._cache.popitem(last=False)
        return prepared

    def at(self, points, t):
        """返回参数 ``t in [0, 1]`` 处的单位切线向量（tuple）。"""
        pts, dim, _ = self._prepared(points)
        u = _validate_t(t)
        return _tangent(pts, dim, u)

    def normal(self, points, t):
        """返回参数 ``t`` 处的二维单位法线（切线逆时针旋转 90°）。"""
        pts, dim, _ = self._prepared(points)
        if dim != 2:
            raise ValueError("法线仅支持二维点")
        u = _validate_t(t)
        tx, ty = _tangent(pts, dim, u)
        return (-ty, tx)

    def arclen_param(self, points, n):
        """按弧长等距重采样为 ``n`` 个点（含两端点），返回 tuple 列表。"""
        pts, dim, total = self._prepared(points)

        if isinstance(n, bool) or not isinstance(n, int):
            raise TypeError("n 必须为整数")
        if n < 2:
            raise ValueError("n 至少为 2")

        m = len(pts)
        cum = [0.0]
        length = 0.0
        for i in range(m - 1):
            a, b = pts[i], pts[i + 1]
            seg_sq = 0.0
            for j in range(dim):
                d = b[j] - a[j]
                seg_sq += d * d
            length += math.sqrt(seg_sq)
            cum.append(length)
        # total 已在校验时计算并保证 > 0；length 与之相等，这里防御性兜底
        if length <= 0.0:
            raise ValueError("退化曲线：总长度为 0")

        out = []
        last = n - 1
        for idx in range(n):
            s = total * idx / last
            seg = bisect.bisect_right(cum, s) - 1
            if seg >= m - 1:
                out.append(pts[-1])
                continue
            if seg < 0:
                seg = 0
            s0, s1 = cum[seg], cum[seg + 1]
            a, b = pts[seg], pts[seg + 1]
            if s1 == s0:
                # 零长段：cum 中存在重复值，bisect 正常情况下不会落入此处
                out.append(tuple(a))
                continue
            f = (s - s0) / (s1 - s0)
            out.append(tuple(a[j] + (b[j] - a[j]) * f for j in range(dim)))
        return out
