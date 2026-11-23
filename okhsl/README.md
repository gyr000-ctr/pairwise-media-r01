# okhsl

## 题面（可直接粘贴）

OKHSL 色彩空间。约束：OKHSL↔sRGB 往返误差 ≤1e-4；色相 360 度闭环；亮度 0/1 时饱和度为 0；色域外颜色要按**保持色相**裁剪（色相偏移 ≤1°）；非法分量与非有限输入要可区分报错；10 万次转换不超过 500 ms；并发安全。验收：cd okhsl && python -m pytest tests -q -k okhsl。

## 边界要求（评审侧隐藏用例判分）

- 并发安全
- 非有限输入分类报错
- 性能上界按题面

## 运行方式

```bash
cd okhsl && python -m pytest tests -q
```

初始 15 failed。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：图像处理
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
