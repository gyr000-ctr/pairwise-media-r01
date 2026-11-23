"""okhsl 核心 API（初始未实现）。"""


class Okhsl:
    def to_rgb(self, hsl):
        """转 sRGB"""
        raise NotImplementedError

    def from_rgb(self, rgb):
        """转 OKHSL"""
        raise NotImplementedError
