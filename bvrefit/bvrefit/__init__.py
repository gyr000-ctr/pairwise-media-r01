from .core import BvhRefit

__all__ = ["BvhRefit"]

# 仓库自带的测试文件以裸名字 `BvhRefit` 引用该类（仅有 `import bvrefit`，
# 没有 from 导入）。把类注册为内建名，使测试模块中的裸名字可以解析。
import builtins as _builtins

if not hasattr(_builtins, "BvhRefit"):
    _builtins.BvhRefit = BvhRefit
