#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
from typing import Optional

import cfg4py
from redis import Redis

logger = logging.getLogger(__file__)


class RedisCache:
    _security_ = 1

    def __init__(self):
        cfg = cfg4py.get_instance()
        self.r = Redis(
            cfg.redis.host,
            cfg.redis.port,
            db=self._security_,
            encoding="utf-8",
            decode_responses=True,
        )

    @property
    def security(self):
        return self.r
