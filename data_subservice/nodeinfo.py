"""节点信息获取（物理解耦版，import _internal，无 backend 依赖）"""

import os
import socket
from typing import Optional

from data_subservice._internal.service_registry import NodeInfo


def get_node_info(region: str = "us-west", capabilities: Optional[list] = None) -> NodeInfo:
    """构建本子节点的 NodeInfo 注册信息。"""
    node_id = os.getenv("NODE_ID", socket.gethostname())
    ip = _get_local_ip()
    port = os.getenv("DATASOURCE_PORT", "8001")
    url = f"http://{ip}:{port}"

    # 优先使用显式入参；否则读 DS_CAPABILITIES（逗号分隔）；再 fallback NODE_CAPABILITIES；
    # 最后 fallback 到与 main._declared_capabilities 保持一致的默认集（含 finnhub/fred/dbnomics/rbi/search）。
    if capabilities is not None:
        raw_caps = capabilities
    else:
        raw_caps = os.getenv("DS_CAPABILITIES") or os.getenv("NODE_CAPABILITIES", "yfinance,akshare,tushare,fmp,futu")
    # 统一按逗号切分（无论 env 字符串还是显式列表）
    if isinstance(raw_caps, str):
        raw_caps = raw_caps.split(",")

    return NodeInfo(
        node_id=node_id,
        url=url,
        region=region,
        weight=int(os.getenv("NODE_WEIGHT", "10")),
        capabilities=[c.strip().lower() for c in raw_caps if str(c).strip()],
        metadata={"ip": ip},
    )


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
