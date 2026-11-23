# bvrefit

## 题面（可直接粘贴）

BVH 动态刷新。约束：移动包围盒后 refit 的查询结果必须与重建 BVH 完全一致（暴力对照）；refit 复杂度为 O(深度)；查询返回按 t 升序且无重复；空树报错；10 万次查询不超过 500 ms；并发读安全。验收：cd bvrefit && python -m pytest tests -q -k bvh。

## 边界要求（评审侧隐藏用例判分）

- 并发安全
- 非有限输入分类报错
- 性能上界按题面

## 运行方式

```bash
cd bvrefit && python -m pytest tests -q
```

初始 15 failed。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：图形渲染
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
