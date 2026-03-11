#!/usr/bin/env python3

"""
Main application entry point for the PyQMT system.
This file sets up the FastHTML application with MonsterUI styling.
"""

import atexit
import os
import sys
from pathlib import Path

from fasthtml.common import *
from monsterui.all import *
from fasthtml.common import Script
from starlette.middleware import Middleware
from starlette.responses import RedirectResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from pyqmt.config import cfg, init_config


def _check_single_instance():
    """检查是否已有实例在运行，防止多实例启动"""
    pid_file = Path(cfg.home) / ".pyqmt.pid"

    if pid_file.exists():
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
                
            if sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(1, False, pid)
                if handle != 0:
                    kernel32.CloseHandle(handle)
                    raise RuntimeError(
                        f"PyQMT 已经在运行 (PID: {pid})。"
                        f"请先停止现有实例，或删除 {pid_file} 后重试。"
                    )
            else:
                # Unix/Linux/Mac
                os.kill(pid, 0)
                raise RuntimeError(
                    f"PyQMT 已经在运行 (PID: {pid})。"
                    f"请先停止现有实例，或删除 {pid_file} 后重试。"
                )
        except (ValueError, OSError, ProcessLookupError):
            # 进程不存在，删除旧文件
            pid_file.unlink()

    # 写入当前 PID
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    # 注册退出时清理
    def cleanup_pid():
        if pid_file.exists():
            pid_file.unlink()

    atexit.register(cleanup_pid)
from pyqmt.core.enums import BrokerKind
from pyqmt.core.errors import BaseTradeError
from pyqmt.core.scheduler import scheduler
from pyqmt.data import init_data
from pyqmt.service.livequote import live_quote
from pyqmt.service.registry import BrokerRegistry
from pyqmt.service.qmt_broker import QMTBroker
from pyqmt.service.sim_broker import SimulationBroker
from pyqmt.web.apis.broker import app as broker_api_app
from pyqmt.web.apis.quotes_ws import app as quotes_ws_app
from pyqmt.web.auth.manager import AuthManager
from pyqmt.web.middleware import BrokerRegistryMiddleware, exception_handler
from pyqmt.web.middleware_init import InitCheckMiddleware
from pyqmt.web.middleware_feature import FeatureCheckMiddleware
from pyqmt.web.pages.init_wizard import init_wizard_app
from pyqmt.web.apis.analysis import index_router, kline_router, search_router, sector_router
from pyqmt.web.pages.init_wizard import init_wizard
from pyqmt.web.pages.accounts import accounts_app, accounts_list
from pyqmt.web.pages.analysis import analysis_handler
from pyqmt.web.pages.history_orders import history_orders_list
from pyqmt.web.pages.history_positions import history_positions_list
from pyqmt.web.pages.history_trades import history_trades_list
from pyqmt.web.pages.home import home_app
from pyqmt.web.pages.live import live_app
from pyqmt.web.pages.login import login_app
from pyqmt.web.pages.strategy import strategy_app
from pyqmt.web.pages.trade import trade_app
from pyqmt.web.pages.trade_main import trade_main_page, set_active_account
from pyqmt.data import db


def _load_accounts_from_db(registry: BrokerRegistry):
    """从数据库加载所有账户到 BrokerRegistry"""
    try:
        # 从数据库加载所有 portfolio
        portfolios = db.get_all_portfolios()
    except RuntimeError as e:
        # 数据库未初始化，跳过账户加载
        print(f"Database not initialized, skipping account loading: {e}")
        return

    for pf in portfolios:
        if pf.kind == BrokerKind.SIMULATION:
            try:
                # 加载已存在的模拟账户
                broker = SimulationBroker.load(pf.portfolio_id)
                registry.register(BrokerKind.SIMULATION, pf.portfolio_id, broker)
            except Exception as e:
                print(f"Failed to load simulation account {pf.portfolio_id}: {e}")


def _create_qmt_broker_if_configured(registry: BrokerRegistry):
    """如果配置了QMT信息，则创建QMT broker实例"""
    from pyqmt.web.pages.init_wizard import init_wizard

    try:
        state = init_wizard.get_state()
    except RuntimeError as e:
        # 数据库未初始化，跳过QMT broker创建
        print(f"Database not initialized, skipping QMT broker creation: {e}")
        return

    # 检查是否配置了QMT账号信息
    if state.qmt_account_id and state.qmt_path:
        try:
            # 创建QMT broker实例
            # 注意：这里应该确保QMTBroker实现了所有抽象方法
            broker = QMTBroker(
                account_id=state.qmt_account_id,
                portfolio_id=state.qmt_account_id
            )

            # 注册到BrokerRegistry
            registry.register(BrokerKind.QMT, state.qmt_account_id, broker)

            print(f"Successfully created and registered QMT broker for account {state.qmt_account_id}")
        except Exception as e:
            print(f"Failed to create QMT broker: {e}")
            print("QMT configuration exists but broker creation failed, user may need to manually configure account")


def _check_xtquant():
    """检查 xtquant 是否可用（当配置为 qmt 模式时）"""
    if cfg.livequote.mode == "qmt":
        try:
            from xtquant import xtdata
        except ImportError as e:
            raise RuntimeError(
                "Configuration requires qmt mode, but xtquant is not installed. "
                "Please install QMT and ensure xtquant is available in your Python environment. "
                f"Original error: {e}"
            ) from e


def init():
    init_config()

    # 检查是否已有实例在运行
    _check_single_instance()

    # 检查 xtquant 可用性
    _check_xtquant()

    init_data(cfg.home)

    scheduler.start()

    live_quote.start()

    reg = BrokerRegistry()

    # 从数据库加载已有账户
    _load_accounts_from_db(reg)
    
    # 尝试创建QMT broker（如果已配置）
    _create_qmt_broker_if_configured(reg)

    auth = AuthManager(config={"login_path": "/login"})

    from pyqmt.web.theme import AppTheme

    app, rt = fast_app(
        hdrs=AppTheme.headers(),
        before=auth.create_beforeware(),
        middleware=[
            Middleware(InitCheckMiddleware),
            Middleware(FeatureCheckMiddleware),
            Middleware(BrokerRegistryMiddleware, registry=reg),
        ],
        exception_handlers={
            Exception: exception_handler,
            BaseTradeError: exception_handler,
        },
        routes=[
            Mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "web" / "static")), name="static"),
            Route("/init-wizard", lambda req: RedirectResponse(f"/init-wizard/?{req.url.query}" if req.url.query else "/init-wizard/")),
            Mount("/init-wizard", init_wizard_app),
            Mount("/login", login_app),
            Mount("/home", home_app),
            Mount("/trade/simulation", trade_app),
            Mount("/trade/live", live_app),
            Route("/trade/positions/history", history_positions_list, methods=["GET"]),
            Route("/trade/orders/history", history_orders_list, methods=["GET"]),
            Route("/trade/records/history", history_trades_list, methods=["GET"]),
            Route("/trade", trade_main_page),
            Route("/trade/", trade_main_page),
            Route("/system/accounts", accounts_list, methods=["GET"]),
            Route("/system/accounts/", accounts_list, methods=["GET"]),
            Mount("/system/accounts", accounts_app),
            Route("/strategy", lambda req: RedirectResponse("/strategy/")),
            Mount("/strategy", strategy_app),
            Route("/analysis", analysis_handler, methods=["GET"]),
            Mount("/broker", broker_api_app),
            # 分析导航 API
            Mount("/api/v1/sectors", sector_router),
            Mount("/api/v1/indices", index_router),
            Mount("/api/v1/kline", kline_router),
            Mount("/api/v1/search", search_router),
            Mount("/ws", quotes_ws_app),
            Mount("/", home_app),
        ],
    )

    auth.initialize(app, prefix="/auth")

    # 添加交易页面路由
    @rt("/trade/set-active", methods=["POST"])
    async def trade_set_active(req, session):
        return await set_active_account(req, session)

    return app


app = init()

if __name__ == "__main__":
    serve()
