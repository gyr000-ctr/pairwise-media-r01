# gridflow

## 题面（可直接粘贴）

网格流场寻路。约束：流场每个格子指向的最优邻居必须与 Dijkstra 一致（含对角代价 √2）；积分路径无碰撞且到达目标；不可达格为 None；512x512 流场不超过 500 ms；非法网格报错；并发安全。验收：cd gridflow && python -m pytest tests -q -k flow。

## 边界要求（评审侧隐藏用例判分）

- 并发安全
- 非有限输入分类报错
- 性能上界按题面

## 运行方式

```bash
cd gridflow && python -m pytest tests -q
```

初始 15 failed。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：游戏开发
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
