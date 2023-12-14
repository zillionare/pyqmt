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
    server_role = os.environ.get(cfg4py.envar)

    if server_role == "DEV":
        _dir = path.normpath(path.join(path.dirname(__file__), "../config"))
    elif server_role == "TEST":
        _dir = path.expanduser("~/.zillionare/pyqmt/config")
    else:
        _dir = path.expanduser("~/zillionare/pyqmt/config")

    sys.path.insert(0, _dir)
    return _dir


def endpoint():
    cfg = cfg4py.get_instance()

    major, minor, *_ = version("zillionare-pyqmt").split(".")
    prefix = cfg.server.prefix.rstrip("/")
    return f"{prefix}/v{major}.{minor}"
