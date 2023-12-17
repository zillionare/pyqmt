#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Author: Aaron-Yang [code@jieyu.ai]
Contributors:

"""
import os
import sys
from importlib.metadata import version
from os import path

import cfg4py


def get_config_dir():
    return os.path.dirname(__file__)


def endpoint():
    cfg = cfg4py.get_instance()

    major, minor, *_ = version("zillionare-pyqmt").split(".")
    prefix = cfg.server.prefix.rstrip("/")
    return f"{prefix}/v{major}.{minor}"

def init_sqlite_db(conn):
    scripts = os.path.join(os.path.dirname(__file__), "../../scripts/sqlite.txt")
    with open(scripts, "r") as f:
        sql = f.read()

        cursor = conn.cursor()
        cursor.executescript(sql)
        conn.commit()
