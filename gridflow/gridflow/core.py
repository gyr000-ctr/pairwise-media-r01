"""gridflow 核心 API（初始未实现）。"""


class GridFlow:
    def build(self, grid, goal):
        """构建流场"""
        raise NotImplementedError

    def next_cell(self, cell):
        """下一格"""
        raise NotImplementedError

    def trace(self, start):
        """积分路径"""
        raise NotImplementedError
