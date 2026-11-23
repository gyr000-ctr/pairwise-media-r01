"""audiocomp 核心 API（初始未实现）。"""


class Comp:
    def __init__(self, threshold, ratio, knee, attack, release):
        """构造"""
        raise NotImplementedError

    def gain_db(self, level_db):
        """静态曲线"""
        raise NotImplementedError

    def process(self, samples):
        """处理"""
        raise NotImplementedError
