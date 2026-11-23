import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def pytest_itemcollected(item):
    # 让验收命令 `pytest -k bvh` 能匹配到本套件（测试 id 本身不含 "bvh"）。
    item.extra_keyword_matches.add("bvh")
