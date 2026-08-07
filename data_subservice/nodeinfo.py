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

    caps = capabilities or os.getenv("NODE_CAPABILITIES", "yfinance,akshare,tushare").split(",")

    return NodeInfo(
        node_id=node_id,
        url=url,
        region=region,
        weight=int(os.getenv("NODE_WEIGHT", "10")),
        capabilities=[c.strip() for c in caps if c.strip()],
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
