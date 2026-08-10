"""
BE-ARCH-07c: 主服务本地枚举常量

主服务已卸载 futu SDK 连接层 (OpenD 直连下沉 data_subservice)。
原 `engine/gateway.py` / `workers/oms/algo_engine.py` 仅引用 `futu.TrdMarket`
与 `futu.TrdSide` 两个枚举, 在此提供与 futu SDK 完全一致的本地等价常量,
使主服务不再 import futu SDK 即可完成交易路由的市场/方向判定。

枚举值严格对齐 futu-api 官方定义, 确保经 DataSourceRouter HTTP 代理下发的
参数与子服务 futu SDK 解析一致。
"""

from enum import IntEnum


class TrdMarket(IntEnum):
    """交易市场 (对齐 futu.TrdMarket)"""

    NONE = 0
    HK = 1
    US = 2
    CN = 3
    HKCC = 4
    Futures = 5
    SG = 6


class TrdSide(IntEnum):
    """交易方向 (对齐 futu.TrdSide)"""

    NONE = 0
    BUY = 1
    SELL = 2
    SELL_SHORT = 3
    BUY_BACK = 4


class ModifyOrderOp(IntEnum):
    """改单/撤单操作 (对齐 futu.ModifyOrderOp)"""

    NONE = 0
    CANCEL = 1
    CANCEL_ALL = 2
    ENABLE = 3
    DISABLE = 4
    DELETE = 5
