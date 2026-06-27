import subprocess
import sys
import time
import os
import socket

def check_port(port):
    """检查端口是否被占用"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        result = sock.connect_ex(('127.0.0.1', port))
        return result == 0
    finally:
        sock.close()

def kill_process_on_port(port):
    """终止占用指定端口的进程（仅 macOS/Linux）"""
    try:
        # 使用 lsof 查找占用端口的进程
        result = subprocess.run(
            ['lsof', '-ti', f':{port}'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            print(f"⚠️  [System] 检测到端口 {port} 被以下进程占用: {', '.join(pids)}")
            print("🔧 [System] 正在清理旧进程...")
            
            for pid in pids:
                pid = pid.strip()
                if pid:
                    try:
                        os.kill(int(pid), 9)
                        print(f"   ✅ 已终止进程 {pid}")
                    except ProcessLookupError:
                        pass
            
            # 等待端口释放
            time.sleep(1)
            return True
        return False
    except Exception as e:
        print(f"⚠️  [System] 无法自动清理端口: {e}")
        print(f"   请手动执行: lsof -ti:{port} | xargs kill -9")
        return False

def main():
    print("🚀 [System] 正在一键启动量化系统双引擎...")
    
    # 0. 检查并清理端口占用
    BACKEND_PORT = 8000
    if check_port(BACKEND_PORT):
        print(f"⚠️  [System] 端口 {BACKEND_PORT} 已被占用")
        if not kill_process_on_port(BACKEND_PORT):
            print(f"❌ [System] 端口 {BACKEND_PORT} 仍被占用，请先手动清理后重试")
            sys.exit(1)
        else:
            print(f"✅ [System] 端口 {BACKEND_PORT} 已释放")
    
    # 1. 创建日志目录，用于存放后端静默日志
    os.makedirs("logs", exist_ok=True)
    backend_log = open("logs/backend.log", "w")
    
    print("📡 [System] 正在启动后端网关 (Data Gateway)...")
    print("   👉 后端运行日志已重定向至: logs/backend.log (防止打断终端打字)")
    
    # 注入环境变量，跳过后端启动时的 YFinance 深度自检，防止与 CLI 自检并发导致 429 封IP
    env = os.environ.copy()
    env["SKIP_YF_TEST"] = "1"

    # 2. 在后台启动 FastAPI (使用 Uvicorn)
    backend_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(BACKEND_PORT), "--reload"],
        stdout=backend_log,
        stderr=subprocess.STDOUT,
        env=env
    )
    
    # 给后端一点时间建立 Redis 和券商连接
    print("⏳ [System] 等待后端服务就绪 (3秒)...")
    time.sleep(3)
    
    if backend_process.poll() is not None:
        print("❌ [System] 后端网关启动失败！请检查 logs/backend.log 查看详细报错原因。")
        sys.exit(1)
        
    print("🖥️  [System] 正在启动前端服务 (Frontend UI)...")
    # 3. 在前台启动前端 Vite 服务
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    frontend_process = subprocess.Popen([npm_cmd, "run", "dev"], cwd=frontend_dir)
    
    try:
        # 阻塞在此，直到用户按 Ctrl+C 退出
        frontend_process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n🛑 [System] 收到终端退出指令，正在清理后台进程...")
        backend_process.terminate()
        frontend_process.terminate()
        backend_log.close()
        print("✅ [System] 所有服务已安全关闭。")

if __name__ == "__main__":
    main()