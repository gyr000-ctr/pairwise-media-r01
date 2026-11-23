"""tangent 核心 API（初始未实现）。"""


class Tangent:
    def at(self, points, t):
        """切线"""
        raise NotImplementedError

    def normal(self, points, t):
        """法线"""
        raise NotImplementedError

    def arclen_param(self, points, n):
        """弧长参数化"""
        raise NotImplementedError
