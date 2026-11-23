"""bvrefit 核心实现：支持 O(深度) 动态 refit 的 BVH。

设计要点：
- 树结构只由 ``add`` 的插入序列与盒位置决定（确定性 binned SAH 构造）；
  ``refit`` 保持结构不变，自叶向根重新计算祖先包围盒，复杂度 O(深度)。
- 查询对命中结果按 (t, 插入序) 排序，输出与树形无关，保证
  "refit 后的查询结果 == 重建后的查询结果 == 暴力对照"。
- 查询只读共享数组（局部栈/结果集），并发读安全；
  写操作（add/build/refit）与惰性重建由同一把锁保护。
"""

from __future__ import annotations

import math
import threading

__all__ = ["BvhRefit"]

_INF = math.inf


def _finite3(v):
    """把输入校验并转换为有限浮点三元组；非法/非有限输入一律 ValueError。"""
    try:
        x = float(v[0])
        y = float(v[1])
        z = float(v[2])
    except (TypeError, ValueError, IndexError, KeyError) as exc:
        raise ValueError(f"invalid 3-component vector: {v!r}") from exc
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        raise ValueError(f"non-finite coordinate in vector: {v!r}")
    return (x, y, z)


def _norm_box(box):
    """校验并规范化 ((minx,miny,minz),(maxx,maxy,maxz))；允许角点次序颠倒。"""
    try:
        lo_raw, hi_raw = box
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid box: {box!r}") from exc
    lo = _finite3(lo_raw)
    hi = _finite3(hi_raw)
    mn = (
        lo[0] if lo[0] < hi[0] else hi[0],
        lo[1] if lo[1] < hi[1] else hi[1],
        lo[2] if lo[2] < hi[2] else hi[2],
    )
    mx = (
        lo[0] if lo[0] > hi[0] else hi[0],
        lo[1] if lo[1] > hi[1] else hi[1],
        lo[2] if lo[2] > hi[2] else hi[2],
    )
    return (mn, mx)


def _sah_split(idxs, cents, boxlist):
    """把一组盒索引确定性地切成两半（binned SAH，三轴取最优）。

    返回值只依赖 (cents, boxlist, idxs) 的内容与顺序，与调用历史无关，
    因此同一插入序列的重建结果完全一致。
    """
    m = len(idxs)
    c0 = [_INF, _INF, _INF]
    c1 = [-_INF, -_INF, -_INF]
    for k in idxs:
        c = cents[k]
        for a in range(3):
            if c[a] < c0[a]:
                c0[a] = c[a]
            if c[a] > c1[a]:
                c1[a] = c[a]
    if m < 8:
        return _median_split(idxs, cents, c0, c1)
    nb = 16
    best_cost = _INF
    best = None
    for axis in range(3):
        lo = c0[axis]
        hi = c1[axis]
        if hi <= lo:
            continue
        scale = nb / (hi - lo)
        bcount = [0] * nb
        bb = [None] * nb
        for k in idxs:
            b = int((cents[k][axis] - lo) * scale)
            if b >= nb:
                b = nb - 1
            bcount[b] += 1
            mn, mx = boxlist[k]
            cur = bb[b]
            if cur is None:
                bb[b] = [mn[0], mn[1], mn[2], mx[0], mx[1], mx[2]]
            else:
                if mn[0] < cur[0]:
                    cur[0] = mn[0]
                if mn[1] < cur[1]:
                    cur[1] = mn[1]
                if mn[2] < cur[2]:
                    cur[2] = mn[2]
                if mx[0] > cur[3]:
                    cur[3] = mx[0]
                if mx[1] > cur[4]:
                    cur[4] = mx[1]
                if mx[2] > cur[5]:
                    cur[5] = mx[2]
        # 右侧后缀计数/包围盒
        rcount = [0] * nb
        rb = [None] * nb
        tot = 0
        acc = None
        for b in range(nb - 1, -1, -1):
            rcount[b] = tot + bcount[b]
            tot += bcount[b]
            cb = bb[b]
            if cb is not None:
                if acc is None:
                    acc = cb[:]
                else:
                    if cb[0] < acc[0]:
                        acc[0] = cb[0]
                    if cb[1] < acc[1]:
                        acc[1] = cb[1]
                    if cb[2] < acc[2]:
                        acc[2] = cb[2]
                    if cb[3] > acc[3]:
                        acc[3] = cb[3]
                    if cb[4] > acc[4]:
                        acc[4] = cb[4]
                    if cb[5] > acc[5]:
                        acc[5] = cb[5]
            if acc is not None:
                rb[b] = acc[:]
        # 自左向右扫描，求每个切分面的 SAH 代价
        lcount = 0
        lb = None
        for b in range(nb - 1):
            cb = bb[b]
            if cb is not None:
                lcount += bcount[b]
                if lb is None:
                    lb = cb[:]
                else:
                    if cb[0] < lb[0]:
                        lb[0] = cb[0]
                    if cb[1] < lb[1]:
                        lb[1] = cb[1]
                    if cb[2] < lb[2]:
                        lb[2] = cb[2]
                    if cb[3] > lb[3]:
                        lb[3] = cb[3]
                    if cb[4] > lb[4]:
                        lb[4] = cb[4]
                    if cb[5] > lb[5]:
                        lb[5] = cb[5]
            rc = rcount[b + 1]
            if lcount == 0 or rc == 0:
                continue
            rbx = rb[b + 1]
            lx = lb[3] - lb[0]
            ly = lb[4] - lb[1]
            lz = lb[5] - lb[2]
            rx = rbx[3] - rbx[0]
            ry = rbx[4] - rbx[1]
            rz = rbx[5] - rbx[2]
            cost = (
                lcount * (lx * ly + ly * lz + lz * lx)
                + rc * (rx * ry + ry * rz + rz * rx)
            )
            if cost < best_cost:
                best_cost = cost
                best = (axis, b, scale, lo)
    if best is None:
        return _median_split(idxs, cents, c0, c1)
    axis, bbin, scale, lo = best
    left_idxs = []
    right_idxs = []
    for k in idxs:
        b = int((cents[k][axis] - lo) * scale)
        if b >= nb:
            b = nb - 1
        if b <= bbin:
            left_idxs.append(k)
        else:
            right_idxs.append(k)
    return left_idxs, right_idxs


def _median_split(idxs, cents, c0, c1):
    """确定性中位切分（质心最长轴，索引决胜）。"""
    ex = c1[0] - c0[0]
    ey = c1[1] - c0[1]
    ez = c1[2] - c0[2]
    if ex >= ey and ex >= ez:
        axis = 0
    elif ey >= ez:
        axis = 1
    else:
        axis = 2
    s = sorted(idxs, key=lambda k: (cents[k][axis], k))
    mid = len(s) // 2
    return s[:mid], s[mid:]


class BvhRefit:
    """动态 BVH：add/build/refit/query。"""

    __slots__ = (
        "_lock",
        "_boxes",
        "_dirty",
        "_bounds",
        "_left",
        "_right",
        "_parent",
        "_name",
        "_order",
        "_leaf_of",
        "_flat",
    )

    def __init__(self):
        self._lock = threading.RLock()
        self._boxes = {}  # name -> (mn, mx)，保持插入序
        self._dirty = True
        # 扁平化节点数组（结构在 build 时确定，refit 只改包围盒分量）
        self._bounds = []   # 每节点 (mnx, mny, mnz, mxx, mxy, mxz)
        self._left = []
        self._right = []
        self._parent = []
        self._name = []     # 叶子为名字，内部节点为 None
        self._order = []    # 叶子的插入序，用于命中排序的稳定决胜
        self._leaf_of = {}
        # 查询热路径一次解包的只读视图
        self._flat = (self._bounds, self._left, self._right,
                      self._name, self._order)

    # ------------------------------------------------------------------ 写操作

    def add(self, name, box):
        """加盒（重名则覆盖）。调用后需 build()；查询前会自动重建。"""
        mn, mx = _norm_box(box)
        with self._lock:
            self._boxes[name] = (mn, mx)
            self._dirty = True

    def build(self):
        """建树（确定性 binned SAH）。"""
        with self._lock:
            self._rebuild()

    def refit(self, name, box):
        """更新一个盒并自叶向根刷新祖先包围盒，复杂度 O(深度)。"""
        mn, mx = _norm_box(box)
        with self._lock:
            if name not in self._boxes:
                raise ValueError(f"unknown box name: {name!r}")
            self._boxes[name] = (mn, mx)
            if self._dirty:
                return  # 尚未建树，下次查询会整体重建
            bounds = self._bounds
            left = self._left
            right = self._right
            parent = self._parent
            i = self._leaf_of[name]
            bounds[i] = (mn[0], mn[1], mn[2], mx[0], mx[1], mx[2])
            i = parent[i]
            while i != -1:
                lb = bounds[left[i]]
                rb = bounds[right[i]]
                nb = (
                    lb[0] if lb[0] < rb[0] else rb[0],
                    lb[1] if lb[1] < rb[1] else rb[1],
                    lb[2] if lb[2] < rb[2] else rb[2],
                    lb[3] if lb[3] > rb[3] else rb[3],
                    lb[4] if lb[4] > rb[4] else rb[4],
                    lb[5] if lb[5] > rb[5] else rb[5],
                )
                if nb == bounds[i]:
                    break  # 祖先包围盒未变，提前结束
                bounds[i] = nb
                i = parent[i]

    # ------------------------------------------------------------------ 建树

    def _rebuild(self):
        # 先在局部变量中完整构建，最后一次性发布（单个引用赋值在 GIL 下
        # 是原子的），保证无锁的并发读者永远看到完整一致的快照。
        boxes = self._boxes
        bounds = []
        left = []
        right = []
        parent = []
        names_arr = []
        order_arr = []
        leaf_of = {}

        names = list(boxes)
        n = len(names)
        if n == 0:
            self._bounds = bounds
            self._left = left
            self._right = right
            self._parent = parent
            self._name = names_arr
            self._order = order_arr
            self._leaf_of = leaf_of
            self._flat = (bounds, left, right, names_arr, order_arr)
            self._dirty = False
            return

        cents = []
        for nm in names:
            mn, mx = boxes[nm]
            cents.append((
                (mn[0] + mx[0]) * 0.5,
                (mn[1] + mx[1]) * 0.5,
                (mn[2] + mx[2]) * 0.5,
            ))
        boxlist = [boxes[nm] for nm in names]

        def make(idxs):
            node = len(bounds)
            bounds.append(None)
            left.append(-1)
            right.append(-1)
            parent.append(-1)
            names_arr.append(None)
            order_arr.append(-1)
            if len(idxs) == 1:
                k = idxs[0]
                nm = names[k]
                mn, mx = boxes[nm]
                bounds[node] = (mn[0], mn[1], mn[2], mx[0], mx[1], mx[2])
                names_arr[node] = nm
                order_arr[node] = k
                leaf_of[nm] = node
                return node
            left_idxs, right_idxs = _sah_split(idxs, cents, boxlist)
            ln = make(left_idxs)
            rn = make(right_idxs)
            left[node] = ln
            right[node] = rn
            parent[ln] = node
            parent[rn] = node
            # 内部节点包围盒 = 子节点包围盒之并（与 refit 的合并完全一致）
            lb = bounds[ln]
            rb = bounds[rn]
            bounds[node] = (
                lb[0] if lb[0] < rb[0] else rb[0],
                lb[1] if lb[1] < rb[1] else rb[1],
                lb[2] if lb[2] < rb[2] else rb[2],
                lb[3] if lb[3] > rb[3] else rb[3],
                lb[4] if lb[4] > rb[4] else rb[4],
                lb[5] if lb[5] > rb[5] else rb[5],
            )
            return node

        make(list(range(n)))
        self._bounds = bounds
        self._left = left
        self._right = right
        self._parent = parent
        self._name = names_arr
        self._order = order_arr
        self._leaf_of = leaf_of
        self._flat = (bounds, left, right, names_arr, order_arr)
        self._dirty = False

    # ------------------------------------------------------------------ 查询

    def query(self, origin, direction, _isfinite=math.isfinite):
        """返回射线与所有盒的命中列表 [(t, name), ...]，按 t 升序、无重复。

        空树（无任何盒）抛 ValueError；非有限输入抛 ValueError。
        """
        try:
            ox = origin[0]
            oy = origin[1]
            oz = origin[2]
            dx = direction[0]
            dy = direction[1]
            dz = direction[2]
            # 快路径：任一分量非有限则总和非有限（inf-inf=nan 亦可捕获）；
            # 有限大数溢出导致的误报走慢路径精确复核。
            finite = _isfinite(ox + oy + oz + dx + dy + dz) or (
                _isfinite(ox)
                and _isfinite(oy)
                and _isfinite(oz)
                and _isfinite(dx)
                and _isfinite(dy)
                and _isfinite(dz)
            )
        except (TypeError, IndexError, KeyError):
            raise ValueError(
                f"invalid origin/direction: {origin!r}, {direction!r}"
            ) from None
        if not finite:
            raise ValueError(
                f"non-finite origin/direction: {origin!r}, {direction!r}"
            )
        if not self._boxes:
            raise ValueError("query on empty BVH (no boxes added)")
        if self._dirty:
            with self._lock:
                if self._dirty:
                    self._rebuild()
        bounds, left, right, names_arr, order_arr = self._flat
        hits = []
        ha = hits.append
        stack = [0]
        pop = stack.pop
        push = stack.append
        while stack:
            i = pop()
            x0, y0, z0, x1, y1, z1 = bounds[i]
            # x 轴 slab
            if dx:
                t1 = (x0 - ox) / dx
                t2 = (x1 - ox) / dx
                if t1 < t2:
                    tmin = t1
                    tmax = t2
                else:
                    tmin = t2
                    tmax = t1
            else:
                if ox < x0 or ox > x1:
                    continue
                tmin = -_INF
                tmax = _INF
            # y 轴 slab
            if dy:
                t1 = (y0 - oy) / dy
                t2 = (y1 - oy) / dy
                if t1 < t2:
                    if t1 > tmin:
                        tmin = t1
                    if t2 < tmax:
                        tmax = t2
                else:
                    if t2 > tmin:
                        tmin = t2
                    if t1 < tmax:
                        tmax = t1
            elif oy < y0 or oy > y1:
                continue
            if tmin > tmax:
                continue
            # z 轴 slab
            if dz:
                t1 = (z0 - oz) / dz
                t2 = (z1 - oz) / dz
                if t1 < t2:
                    if t1 > tmin:
                        tmin = t1
                    if t2 < tmax:
                        tmax = t2
                else:
                    if t2 > tmin:
                        tmin = t2
                    if t1 < tmax:
                        tmax = t1
            elif oz < z0 or oz > z1:
                continue
            if tmin > tmax or tmax < 0.0:
                continue
            nm = names_arr[i]
            if nm is None:
                push(right[i])
                push(left[i])
            else:
                ha((tmin if tmin >= 0.0 else tmax, order_arr[i], nm))
        hits.sort()
        return [(t, nm) for (t, _, nm) in hits]
