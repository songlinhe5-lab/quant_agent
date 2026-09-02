"""通达信协议数据源（mootdx 封装）：盘中快照 / 分时 / 分钟线 / 日线增量。

免费协议源（逆向 TDX 二进制协议，无官方 SLA），盘中 3 秒级快照——
与 baostock 互补：历史深度走 baostock，实时与分钟增量走本源。
SDK 同步 socket：worker 侧必须经 asyncio.to_thread 调用。
mootdx 声明「仅供学习交流」——个人量化项目可用，商业用途前须复核授权。
SDK 延迟导入，未安装 mootdx 的环境可安全 import 本模块。
"""
