import os
import httpx
import json

class SecureAsyncClient(httpx.AsyncClient):
    """
    Agent 工具专属的安全沙箱 HTTP 客户端。
    强制限制 Tool 只能请求内部 Backend 网关，严禁绕过网关直连外部数据源 (如 Yahoo, Futu, Finnhub 等)。
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
        # 允许的内部白名单前缀
        self.allowed_prefixes = (
            self.backend_url,
            "http://127.0.0.1",
            "http://localhost",
            "http://quant_app"  # Docker 内部网络名
        )

    def _verify_url(self, url):
        url_str = str(url)
        if not any(url_str.startswith(prefix) for prefix in self.allowed_prefixes):
            raise PermissionError(
                f"🚨 [风控拦截] 架构越权警告：Agent 严禁直连外部数据源 ({url_str})！只能向后端网关发起请求。"
            )

    async def request(self, method, url, *args, **kwargs):
        self._verify_url(url)
        
        print(f"🌐 [Secure Client] 发起请求: {method} {url} | Payload: {kwargs.get('params') or kwargs.get('json') or {}}")
        response = await super().request(method, url, *args, **kwargs)
        print(f"🌐 [Secure Client] 收到响应: HTTP {response.status_code}")
        
        # 🚨 致命缺陷修复：防御 Agent Token 上下文溢出 (Context Overflow)
        # 若后端接口无意间返回了长达几 MB 的数据（例如筛选出了全市场 3000 只股票），
        # 盲目塞入 Agent 对话历史会瞬间引发 LLM 的 TokenLimitExceeded 导致进程崩溃。
        await response.aread()
        if len(response.content) > 15000:
            try:
                data = response.json()
                # 智能递归截断：保留 JSON 结构完整性，仅对过长的数组进行高位截断
                def truncate_lists(obj):
                    if isinstance(obj, list):
                        if len(obj) > 30:
                            return [truncate_lists(item) for item in obj[:30]] + [{"_notice": "⚠️ 为防止大模型上下文 Token 溢出，后续海量数据已被安全截断！"}]
                        return [truncate_lists(item) for item in obj]
                    elif isinstance(obj, dict):
                        return {k: truncate_lists(v) for k, v in obj.items()}
                    return obj
                
                truncated_data = truncate_lists(data)
                new_content = json.dumps(truncated_data, ensure_ascii=False).encode("utf-8")
                
                # 剔除原有的 content-length，防止重新计算时长度不匹配引发协议报错
                headers = dict(response.headers)
                headers.pop("content-length", None)
                headers.pop("Content-Length", None)
                
                # 使用 httpx.Response 重新打包，无损平替原响应
                response = httpx.Response(
                    status_code=response.status_code,
                    headers=headers,
                    content=new_content,
                    request=response.request,
                )
                print("⚠️ [Secure Client] 响应体积过大，已启动 JSON 结构化安全截断！")
            except Exception:
                pass

        return response