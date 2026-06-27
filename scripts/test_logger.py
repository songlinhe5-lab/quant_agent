import os
import sys
import time

# 将项目根目录加入 sys.path，以便能够正确识别并导入 backend 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.logger import logger

def test_logging_levels():
    print("\n🚀 开始测试 Quant Agent 终端日志高亮...\n")
    
    # 1. 基础级别测试
    logger.debug("这是一个 [DEBUG] 级别的日志：通常用于排查详细的数据结构或后台隐藏的执行步骤。")
    time.sleep(0.3)
    
    logger.info("这是一个 [INFO] 级别的日志：系统正常运行时的关键节点提示，例如接口调用成功。")
    time.sleep(0.3)
    
    logger.warning("这是一个 [WARNING] 级别的日志：出现了非预期情况，但不影响系统主流程，例如接口限流重试。")
    time.sleep(0.3)
    
    logger.error("这是一个 [ERROR] 级别的日志：某个子模块发生了明确的错误，例如网络请求失败！")
    time.sleep(0.3)
    
    logger.critical("这是一个 [CRITICAL] 级别的日志：系统遭遇致命异常，核心服务可能即将崩溃！")
    time.sleep(0.5)
    
    # 2. 异常堆栈 (Traceback) 测试
    print("\n💣 接下来测试捕获异常时的 Rich Traceback 堆栈渲染...\n")
    try:
        logger.info("正在执行一个可能会触发错误的量化指标计算: 100 / 0")
        result = 100 / 0
    except Exception:
        logger.exception("捕获到未处理的计算异常！检查下面的优雅堆栈：")

if __name__ == "__main__":
    test_logging_levels()