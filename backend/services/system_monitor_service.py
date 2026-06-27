import asyncio
import time
from typing import Optional

from backend.core.database import SessionLocal
from backend.core import models
from backend.services.notification_service import notification_service

class SystemMonitorService:
    """
    系统核心监控服务
    负责主事件循环健康探测、性能报警以及慢请求落盘。
    """
    
    def __init__(self):
        self._last_alert_time = 0.0  # 报警防抖状态记录
    
    def _save_performance_log(self, log_type: str, duration_ms: float, endpoint: Optional[str] = None, details: Optional[str] = None):
        """后台线程执行：将性能日志写入数据库 (避免阻塞主事件循环)"""
        try:
            with SessionLocal() as db:
                log_entry = models.PerformanceLog(
                    log_type=log_type,
                    duration_ms=duration_ms,
                    endpoint=endpoint,
                    details=details
                )
                db.add(log_entry)
                db.commit()
        except Exception as e:
            print(f"⚠️ 保存性能日志失败: {e}")

    async def event_loop_monitor_daemon(self):
        """后台高频心跳探针，精确捕获事件循环被同步代码阻塞的延迟时间"""
        interval = 0.1
        tolerance = 0.4  # 超过 400ms 的无响应延迟视为严重阻塞
        while True:
            try:
                start = time.perf_counter()
                await asyncio.sleep(interval)
                delay = (time.perf_counter() - start) - interval
                
                if delay > tolerance:
                    current_time = time.time()
                    db_msg = f"卡顿延迟: {delay * 1000:.0f} ms"
                    
                    # 报警防抖：限制外部通知频率（例如 60 秒内最多推送 1 次）
                    if current_time - self._last_alert_time > 60:
                        self._last_alert_time = current_time
                        print(f"🚨 [性能警报] FastAPI 主事件循环发生严重阻塞！{db_msg}")
                        asyncio.create_task(notification_service.send_alert(f"🚨 [性能警报] FastAPI 主事件循环发生严重阻塞！\n\n{db_msg}"))
                        
                    # 性能日志：所有严重的阻塞依然全量落盘，用于后续排查
                    asyncio.create_task(asyncio.to_thread(self._save_performance_log, "event_loop_block", delay * 1000, None, db_msg))
            except asyncio.CancelledError:
                break

# 导出全局单例
system_monitor_service = SystemMonitorService()