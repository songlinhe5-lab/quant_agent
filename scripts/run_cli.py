import os
import sys
import asyncio
import json
import httpx

# 将项目根目录加入 sys.path，避免 ModuleNotFoundError
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hermes_agent.agent import HermesAgent
from hermes_agent.tool_registry import ToolRegistry

async def check_backend_health(console):
    backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api").rstrip('/')
    console.print(f"\n[bold cyan]🔍 [Pre-flight Check] 正在诊断后端数据网关连通性 ({backend_url})...[/bold cyan]")
    
    endpoints = [
        "/market/quote?ticker=HK.00700",
        "/market/tech-indicators?ticker=HK.00700&lookback_days=1",
        "/market/fundamental/HK.00700",
        "/market/fund-flow?ticker=HK.00700"
    ]
    
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            for ep in endpoints:
                resp = await client.get(f"{backend_url}{ep}")
                if resp.status_code == 200:
                    console.print(f"  [green]✅ HTTP 200 (OK)[/green] {ep}")
                elif resp.status_code in [400, 422]:
                    err_detail = resp.json().get('detail', '未知错误')
                    console.print(f"  [yellow]⚠️ HTTP {resp.status_code} ({err_detail})[/yellow] {ep}")
                elif resp.status_code == 404:
                    console.print(f"  [yellow]⚠️ HTTP 404 (接口尚未实现/暂未挂载)[/yellow] {ep}")
                else:
                    console.print(f"  [red]❌ HTTP {resp.status_code} (内部错误)[/red] {ep}")
    except Exception as e:
        console.print(f"  [bold red]❌ 无法连接到后端网关，请确保 start_all.py 后台服务已就绪！[/bold red] ({str(e).split('(')[0]})")
    console.print()

async def main_cli():
    # 初始化 Hermes Agent
    agent = HermesAgent(
        tool_registry=ToolRegistry(),      # 接入真实的工具网关
        system_prompt_path="AGENTS.md",    # 系统提示词文件路径
        session_id="local_cli_session"     # 终端独立会话 ID
    )
    
    # 💡 初始化并拉取 Redis 记忆
    await agent.initialize()
    
    # 启动前执行自检
    await check_backend_health(agent.console)

    agent.console.print("\n[bold green]🟢 [Terminal] 量化网关 CLI 启动。输入 'exit' 退出，输入 '/clear' 重置历史记忆。[/bold green]")
    while True:
        try:
            user_input = agent.console.input("\n[bold cyan][Trader] 👤:[/bold cyan] ").strip()
            if user_input.lower() in ['exit', 'quit']:
                break
            
            if user_input.lower() == '/clear':
                agent.messages = [{"role": "system", "content": agent.system_prompt}]
                await agent._save_session()
                agent.console.print("\n[bold yellow]🧹 [Memory] 历史记忆已彻底清空，大脑已重置！[/bold yellow]")
                continue
                
            if not user_input:
                continue
                
            agent.console.print("\n[bold green]💬 [Agent Output]:[/bold green] ", end="")
            
            # 调用 agent 的异步流式接口
            async for chunk in agent.chat_stream_async(user_input):
                if chunk["type"] == "text_chunk":
                    # 实时流式输出字符到终端，使用 flush=True 确保不被终端缓冲
                    print(chunk["content"], end="", flush=True)
                elif chunk["type"] == "tool_start":
                    args_str = chunk.get("input", "{}")
                    try:
                        args_formatted = json.dumps(json.loads(args_str), ensure_ascii=False)
                    except:
                        args_formatted = args_str
                    agent.console.print(f"\n[bold magenta]🧠 [Agent Plan] 正在调用工具: {chunk['name']}[/bold magenta] [dim]参数: {args_formatted}[/dim]")
                elif chunk["type"] == "tool_result":
                    # 拦截并格式化打印工具的返回值，对超长的数据进行截断
                    res_str = json.dumps(chunk["result"], ensure_ascii=False, indent=2)
                    if len(res_str) > 500:
                        res_str = res_str[:500] + "\n  ... [数据过长已自动截断以保持终端整洁] ..."
                    agent.console.print(f"[dim cyan]🔧 [Tool Result] 返回数据:[/dim cyan]\n[dim]{res_str}[/dim]")
            
            print() # 本轮回答全部接收完毕，增加一个空行
            
        except (KeyboardInterrupt, EOFError):
            print("\n\n[System] 收到强制中断信号，正在安全关闭...")
            break

if __name__ == "__main__":
    try:
        asyncio.run(main_cli())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass