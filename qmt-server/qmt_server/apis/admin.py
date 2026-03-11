"""Admin UI for qmt-server."""

import datetime

from fasthtml.common import (
    H2,
    H3,
    A,
    Body,
    Button,
    Div,
    Form,
    Head,
    Html,
    Input,
    Label,
    Li,
    Link,
    Main,
    P,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Title,
    Tr,
    Ul,
    fast_app,
)
from qmt_server.runtime import get_sector_sync, get_settings, update_settings
from starlette.requests import Request

from pyqmt.data.dal.sector_dal import SectorDAL
from pyqmt.data.sqlite import db

app, rt = fast_app()


def _layout(content):
    return Html(
        Head(
            Title("qmt-server 管理台"),
            Link(rel="stylesheet", href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css"),
        ),
        Body(Main(content, cls="container")),
    )


def _paginate(total: int, page: int, size: int) -> tuple[int, int, int]:
    pages = max((total + size - 1) // size, 1)
    page = min(max(page, 1), pages)
    start = (page - 1) * size
    return page, pages, start


def _sectors_table(page: int, size: int):
    dal = SectorDAL(db)
    items = [item.to_dict() for item in dal.list_sectors(trade_date=datetime.date.today())]
    page, pages, start = _paginate(len(items), page, size)
    rows = items[start:start + size]
    return Div(
        H3("板块列表"),
        Table(
            Thead(Tr(Th("ID"), Th("名称"), Th("类型"), Th("日期"))),
            Tbody(*[
                Tr(
                    Td(item.get("id", "")),
                    Td(item.get("name", "")),
                    Td(item.get("sector_type", "")),
                    Td(str(item.get("trade_date", ""))),
                )
                for item in rows
            ]),
        ),
        P(f"第 {page}/{pages} 页，共 {len(items)} 条"),
        Div(
            A("上一页", href=f"/admin?page={max(page - 1, 1)}&size={size}"),
            " ",
            A("下一页", href=f"/admin?page={min(page + 1, pages)}&size={size}"),
        ),
    )


def _constituents_table(sector_id: str, page: int, size: int):
    if not sector_id:
        return Div(H3("板块成分股"), P("请输入板块ID后查询"))
    dal = SectorDAL(db)
    items = [item.to_dict() for item in dal.get_sector_stocks(sector_id)]
    page, pages, start = _paginate(len(items), page, size)
    rows = items[start:start + size]
    return Div(
        H3(f"板块成分股 - {sector_id}"),
        Table(
            Thead(Tr(Th("股票"), Th("名称"), Th("权重"), Th("日期"))),
            Tbody(*[
                Tr(
                    Td(item.get("symbol", "")),
                    Td(item.get("name", "")),
                    Td(str(item.get("weight", ""))),
                    Td(str(item.get("trade_date", ""))),
                )
                for item in rows
            ]),
        ),
        P(f"第 {page}/{pages} 页，共 {len(items)} 条"),
        Div(
            A("上一页", href=f"/admin?sector_id={sector_id}&c_page={max(page - 1, 1)}&c_size={size}"),
            " ",
            A("下一页", href=f"/admin?sector_id={sector_id}&c_page={min(page + 1, pages)}&c_size={size}"),
        ),
    )


@rt("/")
async def admin_page(
    request: Request,
    page: int = 1,
    size: int = 20,
    sector_id: str = "",
    c_page: int = 1,
    c_size: int = 30,
    message: str = "",
):
    settings = get_settings()
    default_start = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    default_end = datetime.date.today().isoformat()
    return _layout(
        Div(
            H2("qmt-server 管理台"),
            P(message),
            H3("QMT 配置"),
            Form(
                Label("QMT 账号 ID"),
                Input(name="qmt_account_id", value=settings.qmt_account_id),
                Label("QMT 安装路径"),
                Input(name="qmt_path", value=settings.qmt_path),
                Label("xtdata 路径"),
                Input(name="xtdata_path", value=settings.xtdata_path),
                Button("保存配置", type="submit"),
                method="post",
                action="/admin/settings",
            ),
            H3("数据初始化"),
            Form(
                Label("历史起始日期"),
                Input(name="start_date", type="date", value=default_start),
                Label("历史结束日期"),
                Input(name="end_date", type="date", value=default_end),
                Button("执行初始化下载", type="submit"),
                method="post",
                action="/admin/sync",
            ),
            H3("板块查询"),
            Form(
                Label("板块ID"),
                Input(name="sector_id", value=sector_id),
                Button("查询成分股", type="submit"),
                method="get",
                action="/admin",
            ),
            _sectors_table(page=page, size=size),
            _constituents_table(sector_id=sector_id, page=c_page, size=c_size),
        )
    )


@rt("/settings", methods=["POST"])
async def save_runtime_settings(request: Request):
    form = await request.form()
    update_settings(
        qmt_account_id=str(form.get("qmt_account_id", "")),
        qmt_path=str(form.get("qmt_path", "")),
        xtdata_path=str(form.get("xtdata_path", "")),
    )
    return _layout(
        Div(
            H2("配置保存成功"),
            Ul(
                Li("已更新 QMT/xtdata 路径"),
                Li("已刷新运行时路径"),
            ),
            A("返回管理台", href="/admin"),
        )
    )


@rt("/sync", methods=["POST"])
async def sync_all(request: Request):
    form = await request.form()
    start_date = datetime.date.fromisoformat(str(form.get("start_date")))
    end_date = datetime.date.fromisoformat(str(form.get("end_date")))
    service = get_sector_sync()
    today = datetime.date.today()
    sectors = service.sync_sector_list(trade_date=today)
    constituents = service.sync_sector_constituents(trade_date=today)
    ids = [item.id for item in service.dal.list_sectors(trade_date=today)]
    bars = service.bars_store.fetch_multiple(
        sector_ids=ids,
        start=start_date,
        end=end_date,
    )
    return _layout(
        Div(
            H2("初始化完成"),
            Ul(
                Li(f"板块数量: {sectors}"),
                Li(f"成分股记录: {constituents}"),
                Li(f"行情记录: {bars}"),
            ),
            A("返回管理台", href="/admin"),
        )
    )
