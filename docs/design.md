## 功能

本服务提供以下功能：
### web服务
用以响应客户端的数据请求和交易请求，作为常驻后台程序运行。

### 数据维护：
1. 启动时进行数据追补（从2005年起）
2. 每日下载数据到缓存中

### 提供以下数据接口

endpoint,xt api,说明
security_list, get_stock_list_in_sector,板块成员
calendar,get_trading_dates,日历
sector_list,get_sector_list,板块列表
instrument_type,get_instrument_type,合约类型，即是否为stock, etf等
instrument_detail,get_instrument_detail,获取涨跌停价、流通股本、总股本、IPO、退市日
divid_factors,get_divid_factors,获取除权因子
bars,get_market_data,获取行情数据

除行情数据外，其它数据都不是PIT数据，必须每日获取并进行存储。



## 任务
1. 每日16时，执行各种download_*任务一次
2. 每天盘前订阅一次全推数据，16时取消订阅，以防因mini-qmt重启，而不支持长期订阅

## 数据
1. 初次启动时的数据追赶。使用memo.json记录
