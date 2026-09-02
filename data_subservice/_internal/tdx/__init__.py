"""通达信协议数据源（tdxpy 直连）：盘中快照 / 分时 / 分钟线 / 日线增量。

免费协议源（逆向 TDX 二进制协议，无官方 SLA），盘中 3 秒级快照——
与 baostock 互补：历史深度走 baostock，实时与分钟增量走本源。
SDK 同步 socket：worker 侧必须经 asyncio.to_thread 调用。
直接用 tdxpy（mootdx 的底层库）而非 mootdx：后者已停更且硬钉 httpx<0.26 与项目冲突。
SDK 延迟导入，未安装 tdxpy 的环境可安全 import 本模块。
"""
