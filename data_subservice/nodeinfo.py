"""
==========================================
Data Subservice — 节点信息
==========================================

从环境变量构建节点身份，供心跳上报与被调用方识别。
"""

import os
import socket

from backend.core.service_registry import NodeInfo


def get_node_info() -> NodeInfo:
    node_id = os.getenv("DS_NODE_ID", socket.gethostname())
    region = os.getenv("DS_REGION", "us-west")
    capabilities = [c.strip() for c in os.getenv("DS_CAPABILITIES", "yfinance").split(",") if c.strip()]
    try:
        weight = float(os.getenv("DS_WEIGHT", "10"))
    except ValueError:
        weight = 10.0

    try:
        port = int(os.getenv("DS_NODE_PORT", "8000"))
    except ValueError:
        port = 8000

    base_url = os.getenv("DS_BASE_URL", "")
    if not base_url:
        base_url = f"http://{os.getenv('PUBLIC_IP', socket.gethostname())}:{port}"

    return NodeInfo(
        node_id=node_id,
        url=base_url,
        region=region,
        weight=int(weight) if weight == int(weight) else int(weight),
        capabilities=capabilities,
    )
