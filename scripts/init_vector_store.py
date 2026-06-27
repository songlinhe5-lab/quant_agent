import json
import os
from sqlalchemy import create_engine, text

# 1. 数据库连接配置
# 建议通过环境变量配置连接字符串，或在此处替换为真实的连接地址
DB_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://username:password@localhost:5432/your_database")
engine = create_engine(DB_URL)

def reset_and_init_vector_store(rules_data):
    """
    全量刷新向量存储：在一个事务中清空旧数据并插入新数据。
    如果发生错误，所有操作将自动回滚。
    """
    # engine.begin() 会自动开启事务，并在 with 代码块结束时自动 commit
    # 如果内部抛出异常，则会自动 rollback
    try:
        with engine.begin() as conn:
            print("-> 开始数据库事务...")
            
            # 第 1 步：清空旧数据 (TRUNCATE)
            # 使用 TRUNCATE 比 DELETE 快得多，并且不会产生大量的 WAL 日志
            print("-> 正在清空 quant_screener_rules 表...")
            conn.execute(text("TRUNCATE TABLE quant_screener_rules"))
            
            # 第 2 步：插入新数据
            # SQLAlchemy 推荐使用 :参数名 的形式进行传参
            insert_stmt = text("""
                INSERT INTO quant_screener_rules (id, desc_text, rule_text, rule_type, embedding)
                VALUES (:id, :desc, :rule, :rtype, CAST(:emb AS vector))
            """)
            
            print(f"-> 正在插入 {len(rules_data)} 条新规则及向量数据...")
            # 传入字典列表，SQLAlchemy 会自动进行批量插入 (executemany)，性能很高
            conn.execute(insert_stmt, rules_data)
            
            print("-> 操作成功，事务已自动提交！")
            
    except Exception as e:
        print(f"-> [错误] 数据库初始化失败，已自动回滚！错误详情: {e}")


# ===== 使用示例 =====
if __name__ == "__main__":
    # 模拟你生成的规则和向量数据
    # 根据你之前的错误日志，你的 emb 字段传入的是字符串格式的列表
    # (例如: "[-0.011032, -0.005654, ...]")
    # 结合 SQL 语句中的 CAST(:emb AS vector)，这种传参方式是非常标准且稳妥的
    
    mock_new_rules = [
        {
            "id": "rule_0",
            "desc": "毛利率 gross margin",
            "rule": "- 毛利率(gross_margin) -> GROSS_PROFIT_RATIO (financial)",
            "rtype": "financial",
            "emb": str([-0.011032024, -0.005654132, -0.036064200])  # 将 Python list 转换为 "[...]" 字符串
        },
        {
            "id": "rule_1",
            "desc": "净利润 net profit",
            "rule": "- 净利润 -> NET_PROFIT_RATIO (financial)",
            "rtype": "financial",
            "emb": str([0.021032024, 0.015654132, -0.016064200])
        }
    ]
    
    # 执行初始化
    reset_and_init_vector_store(mock_new_rules)
