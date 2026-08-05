"""
==========================================
Data Source Proxy Router - 数据源代理路由
==========================================

提供数据源代理接口，允许其他节点通过 HTTP 调用本地数据源。

安全机制（公网暴露时必须启用）：
1. HMAC 签名验证（防止请求篡改）
2. 时间戳防重放攻击（±5分钟窗口）
3. IP 白名单（仅允许已知节点 IP 访问）
4. 请求频率限制（防 DDoS）

环境变量配置：
  DATA_SOURCE_HMAC_SECRET=...           # HMAC 签名密钥
  DATA_SOURCE_ALLOWED_IPS=1.2.3.4,5.6.7.8  # 允许的 IP 列表（逗号分隔）
  DATA_SOURCE_RATE_LIMIT=100/minute     # 请求频率限制
"""

from fastapi import APIRouter

router = APIRouter(prefix="/data-source", tags=["Data Source Health"])

# ───────────────────────────────────────────────────────────────
# 修复3 (剥离 yfinance): 已删除主服务遗留的 /proxy/yfinance、/proxy/akshare
# 代理端点。数据源代理能力已物理解耦到独立数据子服务 data_subservice
# (统一 /api/v1/data 端点, 由主服务经 DataSourceRouter 走 HMAC 调用)。
# 见 commit 93f1ecf (删除 data_subservice/routes.py) 与 docs/14。
# ───────────────────────────────────────────────────────────────


@router.get("/health")
async def data_source_health():
    """数据源健康检查（仅探测主服务本地 yfinance / akshare 适配器可用性）。

    注: 实际的跨节点代理请求已由 data_subservice 承接, 本端点不做代理转发。
    """
    from backend.app.market_data import market_data

    return {
        "status": "healthy",
        "yfinance": market_data.yf_health_status(),
        "akshare": market_data.ak_health_status(),
    }
