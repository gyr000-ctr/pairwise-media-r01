"""bvrefit 核心 API（初始未实现）。"""


class BvhRefit:
    def add(self, name, box):
        """加盒"""
        raise NotImplementedError

    def build(self):
        """建树"""
        raise NotImplementedError

    def refit(self, name, box):
        """更新"""
        raise NotImplementedError

    def query(self, origin, direction):
        """查询"""
        raise NotImplementedError
