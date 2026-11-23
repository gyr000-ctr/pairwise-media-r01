import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# 占位用例 test_spec 的 smoke 分支直接引用了 Tangent 名字，
# 而测试模块只做了 ``import tangent``，在收集阶段将其注入测试命名空间。
import tangent  # noqa: E402


def pytest_collection_modifyitems(items):
    for item in items:
        module = getattr(item, "module", None)
        if module is not None and not hasattr(module, "Tangent"):
            module.Tangent = tangent.Tangent
