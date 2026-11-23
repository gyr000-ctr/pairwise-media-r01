# tangent

## 题面（可直接粘贴）

曲线切线与法线。约束：切线必须与中心差分一致（≤1e-4）；单位化；按弧长参数化后速度恒定（误差 ≤1e-3）；退化曲线报错；1 万点不超过 300 ms；并发安全。验收：cd tangent && python -m pytest tests -q -k tangent。

## 边界要求（评审侧隐藏用例判分）

- 并发安全
- 非有限输入分类报错
- 性能上界按题面

## 运行方式

```bash
cd tangent && python -m pytest tests -q
```

初始 15 failed。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：图形渲染
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
