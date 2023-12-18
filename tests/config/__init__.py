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

from pyqmt.dal.ch import ClickHouse

TABLE_PARAMETER = "{TABLE_PARAMETER}"
DROP_TABLE_SQL = f"DROP TABLE {TABLE_PARAMETER};"
GET_TABLES_SQL = "SELECT name FROM sqlite_schema WHERE type='table';"


def get_config_dir():
    return os.path.dirname(__file__)


def endpoint():
    cfg = cfg4py.get_instance()

    major, minor, *_ = version("zillionare-pyqmt").split(".")
    prefix = cfg.server.prefix.rstrip("/")
    return f"{prefix}/v{major}.{minor}"


def get_chores_tables(con):
    cur = con.cursor()
    cur.execute(GET_TABLES_SQL)
    tables = cur.fetchall()
    cur.close()
    return tables


def drop_chores_tabels(con, tables):
    cur = con.cursor()
    for (table,) in tables:
        if table == "sqlite_sequence":
            continue

        sql = DROP_TABLE_SQL.replace(TABLE_PARAMETER, table)
        cur.execute(sql)
    cur.close()


def init_chores_db(conn):
    tables = get_chores_tables(conn)
    drop_chores_tabels(conn, tables)

    scripts = os.path.join(os.path.dirname(__file__), "../../scripts/sqlite.txt")
    with open(scripts, "r", encoding="utf-8") as f:
        sql = f.read()

        cursor = conn.cursor()
        cursor.executescript(sql)
        conn.commit()

def init_haystore():
    cfg = cfg4py.init(get_config_dir())
    haystore = ClickHouse()
    haystore.connect()

    cmd = "truncate database if exists tests"
    haystore.client.command(cmd)

    # create tables
    scripts = os.path.join(os.path.dirname(__file__), "../../scripts/clickhouse.txt")
    with open(scripts, "r", encoding='utf-8') as f:
        content = f.read()

        for sql in content.split("\n\n"):
            if len(sql) < 5:
                continue
            haystore.client.command(sql)

    cfg.haystore = haystore
