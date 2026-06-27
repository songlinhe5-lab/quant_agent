import os
import sys
from sqlalchemy import text

# 确保脚本可以引用到外层的模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core.database import engine

def migrate():
    print("🚀 开始迁移数据库，为 screener_subscriptions 添加新字段...")
    # 使用 engine.begin() 自动管理事务提交
    with engine.begin() as conn:
        try:
            # SQLite 和 PostgreSQL 均支持该基础的 ADD COLUMN 语法
            conn.execute(text("ALTER TABLE screener_subscriptions ADD COLUMN trigger_time VARCHAR(5) DEFAULT '18:00'"))
            print("✅ 成功添加列: trigger_time")
        except Exception as e:
            print(f"⚠️ 添加 trigger_time 失败 (可能已存在): {e}")
            
        try:
            conn.execute(text("ALTER TABLE screener_subscriptions ADD COLUMN last_triggered_at DATETIME"))
            print("✅ 成功添加列: last_triggered_at")
        except Exception as e:
            print(f"⚠️ 添加 last_triggered_at 失败 (可能已存在): {e}")
            
    print("🎉 数据库表结构升级完成！")
    
    engine.dispose()

if __name__ == "__main__":
    migrate()