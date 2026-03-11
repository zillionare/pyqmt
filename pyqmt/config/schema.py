# noqa
from typing import Any
import datetime


class Config(object):
    __access_counter__ = 0

    def __cfg4py_reset_access_counter__(self):
        self.__access_counter__ = 0

    def __getattribute__(self, name):
        obj = object.__getattribute__(self, name)
        if name.startswith("__") and name.endswith("__"):
            return obj

        if callable(obj):
            return obj

        self.__access_counter__ += 1
        return obj

    def __init__(self):
        raise TypeError("Do NOT instantiate this class")

    class server:
        key: str

        host: str

        port: int

        prefix: str

    users: list

    class apikeys:
        timeout: int

        clients: list

    class livequote:
        mode: str

        class qmt:
            path: str
            markets: list

    brokers: list

    class qmt:
        account_id: str

        account_type: str

        name: str

        path: str

        principal: int

    class notify:
        class dingtalk:
            access_token: str

            secret: str

            keyword: str

        class mail:
            mail_to: str

            mail_from: str

            mail_server: str

    home: str

    epoch: datetime.date
