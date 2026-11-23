# audiocomp

## 题面（可直接粘贴）

压缩器（含软拐点）。约束：增益曲线必须与解析公式一致（误差 ≤1e-9）；软拐点两端一阶连续；attack/release 用指数平滑且跨缓冲连续；无爆音；100 万样本不超过 400 ms；非法参数要可区分报错。验收：cd audiocomp && python -m pytest tests -q -k comp。

## 边界要求（评审侧隐藏用例判分）

- 并发安全
- 非有限输入分类报错
- 性能上界按题面

## 运行方式

```bash
cd audiocomp && python -m pytest tests -q
```

初始 15 failed。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：音视频处理
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
