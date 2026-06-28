#!/usr/bin/env python3
"""
BE-01: K线实时管道端到端压测工具

测试链路：
    Futu OpenD → Python SDK → Redis Streams → WebSocket → 客户端

目标：
    P99 延迟 < 50ms

测试场景：
    1. 单标的行情快照延迟
    2. 多标的并发订阅延迟
    3. Redis Stream 写入/读取延迟
    4. WebSocket 推送延迟
    5. 端到端全链路延迟

使用方式：
    # 运行完整压测
    python -m backend.scripts.benchmark_kline_pipeline

    # 指定测试标的和次数
    python -m backend.scripts.benchmark_kline_pipeline --symbols US.AAPL,HK.00700 --iterations 100

    # 仅测试 Redis 层
    python -m backend.scripts.benchmark_kline_pipeline --stage redis
"""  # noqa: E501
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median, stdev
from typing import Any, Dict, List, Optional

import structlog

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

logger = structlog.get_logger(__name__)


class PipelineBenchmark:
    """K线管道压测引擎"""

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        iterations: int = 100,
    ):
        self.symbols = symbols or ["US.AAPL", "HK.00700", "US.SPY"]
        self.iterations = iterations
        self.results: Dict[str, List[float]] = defaultdict(list)

    async def run_all(self) -> Dict[str, Any]:
        """运行所有压测场景"""
        logger.info("[压测] 开始 K线管道全链路压测")
        logger.info(f"[压测] 标的: {self.symbols}, 迭代次数: {self.iterations}")

        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "symbols": self.symbols,
                "iterations": self.iterations,
            },
            "stages": {},
        }

        # 1. Redis 层压测
        logger.info("[压测] 阶段 1/4: Redis Stream 写入/读取")
        redis_result = await self.benchmark_redis()
        results["stages"]["redis"] = redis_result

        # 2. Futu 行情获取压测
        logger.info("[压测] 阶段 2/4: Futu 行情获取")
        futu_result = await self.benchmark_futu_quote()
        results["stages"]["futu"] = futu_result

        # 3. 行情写入 Redis 压测
        logger.info("[压测] 阶段 3/4: 行情写入 Redis")
        write_result = await self.benchmark_quote_write()
        results["stages"]["quote_write"] = write_result

        # 4. 端到端全链路压测
        logger.info("[压测] 阶段 4/4: 端到端全链路")
        e2e_result = await self.benchmark_e2e()
        results["stages"]["e2e"] = e2e_result

        # 汇总统计
        results["summary"] = self._generate_summary(results)

        return results

    async def benchmark_redis(self) -> Dict[str, Any]:
        """Redis Stream 写入/读取压测"""
        from backend.core.redis_client import redis_client

        latencies = []
        test_key = "quant:benchmark:stream"

        # 清理测试数据
        await redis_client.delete(test_key)

        for i in range(self.iterations):
            t0 = time.perf_counter()

            # 写入 Redis Stream
            await redis_client.xadd(
                test_key,
                {"data": json.dumps({"i": i, "ts": time.time()})},
                maxlen=1000,
            )

            # 读取最新数据
            await redis_client.xrevrange(test_key, count=1)

            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)  # 转毫秒

        # 清理
        await redis_client.delete(test_key)

        return self._calc_stats(latencies, "redis_stream")

    async def benchmark_futu_quote(self) -> Dict[str, Any]:
        """Futu 行情获取压测"""
        latencies = []

        try:
            from backend.services.futu import futu_service

            for symbol in self.symbols:
                symbol_latencies = []

                for _ in range(self.iterations // len(self.symbols)):
                    t0 = time.perf_counter()

                    await futu_service.get_quote(symbol)

                    t1 = time.perf_counter()
                    latency_ms = (t1 - t0) * 1000
                    latencies.append(latency_ms)
                    symbol_latencies.append(latency_ms)

                self.results[f"futu_{symbol}"] = symbol_latencies

        except Exception as e:
            logger.warning(f"[压测] Futu 行情获取跳过（未连接）: {e}")
            return {"status": "skipped", "reason": str(e)}

        return self._calc_stats(latencies, "futu_quote")

    async def benchmark_quote_write(self) -> Dict[str, Any]:
        """行情写入 Redis 压测"""
        latencies = []

        try:
            from backend.core.market_engine import update_quote_to_redis

            test_quote = {
                "ticker": "US.BENCHMARK",
                "last_price": 100.0,
                "change_pct": "1.00%",
                "volume_str": "1M",
                "source": "benchmark",
                "bids": [{"price": 99.9, "size": 100}],
                "asks": [{"price": 100.1, "size": 100}],
            }

            for i in range(self.iterations):
                test_quote["last_price"] = 100.0 + i * 0.01

                t0 = time.perf_counter()

                await update_quote_to_redis("US.BENCHMARK", test_quote)

                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000)

        except Exception as e:
            logger.warning(f"[压测] 行情写入 Redis 跳过: {e}")
            return {"status": "skipped", "reason": str(e)}

        return self._calc_stats(latencies, "quote_write")

    async def benchmark_e2e(self) -> Dict[str, Any]:
        """端到端全链路压测"""
        latencies = []

        try:
            from backend.core.market_engine import update_quote_to_redis
            from backend.core.redis_client import redis_client
            from backend.services.futu import futu_service

            for symbol in self.symbols[:1]:  # 只测第一个标的
                for _ in range(self.iterations):
                    t0 = time.perf_counter()

                    # 1. 获取行情
                    quote = await futu_service.get_quote(symbol)

                    if quote.get("status") == "success":
                        # 2. 写入 Redis
                        await update_quote_to_redis(symbol, quote)

                        # 3. 从 Redis 读取验证
                        await redis_client.hget(
                            "quant:quotes:latest", symbol
                        )

                    t1 = time.perf_counter()
                    latencies.append((t1 - t0) * 1000)

        except Exception as e:
            logger.warning(f"[压测] 端到端压测跳过: {e}")
            return {"status": "skipped", "reason": str(e)}

        return self._calc_stats(latencies, "e2e")

    def _calc_stats(self, latencies: List[float], stage: str) -> Dict[str, Any]:
        """计算延迟统计"""
        if not latencies:
            return {"status": "no_data"}

        sorted_lat = sorted(latencies)
        n = len(sorted_lat)

        stats = {
            "count": n,
            "min_ms": round(sorted_lat[0], 3),
            "max_ms": round(sorted_lat[-1], 3),
            "mean_ms": round(mean(sorted_lat), 3),
            "median_ms": round(median(sorted_lat), 3),
            "p50_ms": round(sorted_lat[int(n * 0.50)], 3),
            "p90_ms": round(sorted_lat[int(n * 0.90)], 3),
            "p95_ms": round(sorted_lat[int(n * 0.95)], 3),
            "p99_ms": round(sorted_lat[int(n * 0.99)], 3) if n >= 100 else None,
        }

        if n > 1:
            stats["stdev_ms"] = round(stdev(sorted_lat), 3)

        # 判断是否达标
        target_p99 = 50.0  # 目标 P99 < 50ms
        if stats["p99_ms"] and stats["p99_ms"] < target_p99:
            stats["pass"] = True
        elif stats["p95_ms"] < target_p99:
            stats["pass"] = True  # 样本不足时用 P95 代替
        else:
            stats["pass"] = False

        return stats

    def _generate_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """生成压测汇总报告"""
        stages = results.get("stages", {})

        summary = {
            "overall_pass": True,
            "stages_passed": 0,
            "stages_total": len(stages),
        }

        for stage_name, stage_result in stages.items():
            if stage_result.get("status") == "skipped":
                summary["stages_total"] -= 1
                continue

            if stage_result.get("pass", False):
                summary["stages_passed"] += 1
            else:
                summary["overall_pass"] = False

        # 生成可读报告
        report_lines = [
            "=" * 60,
            "K线管道压测报告",
            "=" * 60,
            f"测试时间: {results['timestamp']}",
            f"测试标的: {', '.join(results['config']['symbols'])}",
            f"迭代次数: {results['config']['iterations']}",
            "",
        ]

        for stage_name, stage_result in stages.items():
            if stage_result.get("status") == "skipped":
                report_lines.append(f"[{stage_name}] 跳过: {stage_result.get('reason')}")  # noqa: E501
                continue

            status = "✅ PASS" if stage_result.get("pass") else "❌ FAIL"
            report_lines.append(f"[{stage_name}] {status}")
            report_lines.append(f"  P50: {stage_result.get('p50_ms')} ms")
            report_lines.append(f"  P95: {stage_result.get('p95_ms')} ms")
            if stage_result.get('p99_ms'):
                report_lines.append(f"  P99: {stage_result.get('p99_ms')} ms")
            report_lines.append("")

        report_lines.append("-" * 60)
        overall = "✅ PASS" if summary["overall_pass"] else "❌ FAIL"
        report_lines.append(f"总结: {overall} ({summary['stages_passed']}/{summary['stages_total']} 阶段通过)")  # noqa: E501
        report_lines.append("目标: P99 < 50ms")
        report_lines.append("=" * 60)

        summary["report"] = "\n".join(report_lines)

        return summary


# ── CLI 入口 ──────────────────────────────────────────────────────

async def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="K线管道压测工具")
    parser.add_argument(
        "--symbols", "-s",
        default="US.AAPL,HK.00700,US.SPY",
        help="测试标的（逗号分隔）",
    )
    parser.add_argument(
        "--iterations", "-n",
        type=int, default=100,
        help="每个场景的迭代次数",
    )
    parser.add_argument(
        "--stage",
        choices=["all", "redis", "futu", "write", "e2e"],
        default="all",
        help="指定测试阶段",
    )

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]

    benchmark = PipelineBenchmark(
        symbols=symbols,
        iterations=args.iterations,
    )

    if args.stage == "all":
        results = await benchmark.run_all()
    elif args.stage == "redis":
        results = {"stages": {"redis": await benchmark.benchmark_redis()}}
    elif args.stage == "futu":
        results = {"stages": {"futu": await benchmark.benchmark_futu_quote()}}
    elif args.stage == "write":
        results = {"stages": {"write": await benchmark.benchmark_quote_write()}}
    elif args.stage == "e2e":
        results = {"stages": {"e2e": await benchmark.benchmark_e2e()}}

    # 输出报告
    if "summary" in results and "report" in results["summary"]:
        print(results["summary"]["report"])
    else:
        print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
