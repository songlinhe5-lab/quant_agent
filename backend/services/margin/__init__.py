"""融资融券余额数据服务

提供 A 股、港股、美股三个市场的融资融券余额数据聚合服务。
数据来源:
- A 股: AKShare (上交所/深交所)
- 港股: Futu API
- 美股: FINRA / YFinance
"""

from backend.services.margin.service import MarginService

__all__ = ["MarginService"]
