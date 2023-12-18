from typing import Optional


class XtQuantError(Exception):
    """xt错误基类"""

    def __init__(self, msg: str, error_code: Optional[int] = None):
        if error_code is not None:
            self.error_code = error_code
        self.msg = msg

    def __str__(self):
        return f"{self.__class__.__name__}({self.error_code}: {self.msg})"

    @classmethod
    def parse_msg(cls, msg: str) -> "XtQuantError":
        """从xtquant的错误消息中，解析出具体的Error class"""
        if msg.startswith("行情服务连接断开"):
            return XtDisconnected(msg)
        elif msg.startswith("下载数据失败："):
            try:
                msg, error_code = msg.split(":")
                return XtDownloadDataError(msg, error_code)
            except:
                return XtDownloadDataError(msg)
        else:
            return XtQuantError(msg)


class XtDisconnected(XtQuantError):
    pass


class XtDownloadDataError(XtQuantError):
    pass
