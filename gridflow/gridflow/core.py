"""gridflow 核心 API。

基于 Dijkstra 的网格流场（flow field）寻路：

- 从目标格反向执行 8 邻域 Dijkstra，直边代价 1、对角代价 √2；
- 每个可达格在距离松弛时记录最优邻居（父节点），因此流场指向
  与 Dijkstra 最短路径树严格一致；
- 不可达格（以及目标格自身）的下一格为 ``None``；
- ``build`` 每次生成全新的不可变数组并原子发布，读操作仅做快照，
  因而与并发的重建/读取互不干扰（线程安全）。
"""

import heapq
import math
import threading

__all__ = ["GridFlow"]

_SQRT2 = math.sqrt(2.0)
_INF = math.inf

# (dx, dy, 边代价)，按 (dy, dx) 行主序枚举，与常规参考 Dijkstra 的
# 邻居遍历顺序一致；严格小于的松弛策略保留首个最优邻居，保证平局
# 裁决确定且与参考实现相同。
_NEIGHBORS = (
    (-1, -1, _SQRT2),
    (0, -1, 1.0),
    (1, -1, _SQRT2),
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (-1, 1, _SQRT2),
    (0, 1, 1.0),
    (1, 1, _SQRT2),
)


def _is_real_number(value):
    """仅接受有限的 int/float（bool 作为 int 的子类可接受）。"""
    return isinstance(value, (int, float)) and math.isfinite(value)


class GridFlow:
    def __init__(self):
        self._lock = threading.RLock()
        self._w = 0
        self._h = 0
        self._goal = -1
        self._next = []  # 扁平下标，-1 表示无下一格（目标或不可达）

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def build(self, grid, goal):
        """根据网格 ``grid`` 与目标 ``goal=(x, y)`` 构建流场。

        网格为行列等长的二维序列，数值 0 表示可通行、非 0 有限值表示
        障碍；空网格、异形网格、非数值/非有限值、非法目标均抛出
        :class:`ValueError`。
        """
        # ---- 校验网格形状与元素 ----
        if not isinstance(grid, (list, tuple)) or len(grid) == 0:
            raise ValueError("grid 必须为非空的二维序列")
        h = len(grid)
        first = grid[0]
        if not isinstance(first, (list, tuple)) or len(first) == 0:
            raise ValueError("grid 必须为非空的二维序列")
        w = len(first)

        n = w * h
        blocked = bytearray(n)
        for y, row in enumerate(grid):
            if not isinstance(row, (list, tuple)) or len(row) != w:
                raise ValueError("grid 各行必须等长（不支持异形网格）")
            base = y * w
            for x, value in enumerate(row):
                if not _is_real_number(value):
                    raise ValueError(
                        "grid 元素必须为有限数值，发现非法值: %r" % (value,)
                    )
                if value != 0:
                    blocked[base + x] = 1

        # ---- 校验目标 ----
        if not isinstance(goal, (list, tuple)) or len(goal) != 2:
            raise ValueError("goal 必须为 (x, y) 二元组")
        gx, gy = goal
        if type(gx) is not int or type(gy) is not int:
            raise ValueError("goal 坐标必须为整数")
        if not (0 <= gx < w and 0 <= gy < h):
            raise ValueError("goal 超出网格范围")
        start = gy * w + gx
        if blocked[start]:
            raise ValueError("goal 不能位于障碍格")

        # ---- 反向 Dijkstra（目标为源点）----
        dist = [_INF] * n
        nxt = [-1] * n
        dist[start] = 0.0
        # 堆键含 (x, y)：等距节点按坐标序弹出，与常规 (d, x, y) 参考
        # 实现的平局处理一致，保证父指针（最优邻居）逐格相同
        heap = [(0.0, gx, gy)]
        heappop = heapq.heappop
        heappush = heapq.heappush
        neighbors = _NEIGHBORS

        while heap:
            d, x, y = heappop(heap)
            idx = y * w + x
            if d != dist[idx]:
                continue  # 过期的松弛记录
            for dx, dy, cost in neighbors:
                nx = x + dx
                if nx < 0 or nx >= w:
                    continue
                ny = y + dy
                if ny < 0 or ny >= h:
                    continue
                nidx = ny * w + nx
                if blocked[nidx]:
                    continue
                if dx and dy:
                    # 禁止对角穿越墙角：两个正交邻格必须都可通行，
                    # 否则该对角步视为碰撞
                    if blocked[idx + dx] or blocked[idx + dy * w]:
                        continue
                nd = d + cost
                if nd < dist[nidx]:
                    dist[nidx] = nd
                    nxt[nidx] = idx  # 最优邻居（父节点）
                    heappush(heap, (nd, nx, ny))

        # ---- 原子发布：旧数组不再被触碰，并发读始终看到一致快照 ----
        with self._lock:
            self._w = w
            self._h = h
            self._goal = start
            self._next = nxt
        return self

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def _snapshot(self):
        with self._lock:
            return self._w, self._h, self._goal, self._next

    def _resolve_cell(self, cell, w, h):
        if not isinstance(cell, (list, tuple)) or len(cell) != 2:
            raise ValueError("cell 必须为 (x, y) 二元组")
        x, y = cell
        if type(x) is not int or type(y) is not int:
            raise ValueError("cell 坐标必须为整数")
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError("cell 超出网格范围")
        return y * w + x

    def next_cell(self, cell):
        """返回流场指向的下一格 ``(x, y)``；目标格与不可达格返回 ``None``。"""
        w, h, _goal, nxt = self._snapshot()
        if w == 0:
            raise ValueError("流场尚未构建，请先调用 build")
        idx = self._resolve_cell(cell, w, h)
        parent = nxt[idx]
        if parent < 0:
            return None
        return (parent % w, parent // w)

    def trace(self, start):
        """从 ``start`` 沿流场积分出到达目标的路径（含起点与目标）。

        路径只经过可通行格；起点不可达时返回空列表，起点即目标时
        返回仅含该格的列表。
        """
        w, h, goal, nxt = self._snapshot()
        if w == 0:
            raise ValueError("流场尚未构建，请先调用 build")
        idx = self._resolve_cell(start, w, h)

        if nxt[idx] < 0:
            # 目标格 -> 单点路径；不可达格 -> 空路径
            return [(idx % w, idx // w)] if idx == goal else []

        path = [(idx % w, idx // w)]
        limit = w * h + 1  # 防御性上限：Dijkstra 父节点距离严格递减，不可能成环
        for _ in range(limit):
            idx = nxt[idx]
            path.append((idx % w, idx // w))
            if nxt[idx] < 0:
                return path
        raise RuntimeError("流场出现环路（不应发生）")
