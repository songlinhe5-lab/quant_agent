"""BaoStock 物理解耦数据源（A股历史 K 线 / 季频财务 / 复权因子）。

免费协议源（自研 TCP，需 login 长连接），T+1 更新、无实时行情——
定位：历史深度与稳定财务指标；盘中快照走 tdx（mootdx）。
SDK 为同步阻塞 API：worker 侧必须经 asyncio.to_thread 调用，禁止直接进事件循环。
SDK 延迟导入（函数内 import），未安装 baostock 的环境（主服务/纯 yfinance 叶子节点）可安全 import 本模块。
"""
