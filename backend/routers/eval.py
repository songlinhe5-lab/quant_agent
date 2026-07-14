"""
AI-03 · Eval API 端点

- POST /eval/run — 触发全量 eval 运行
- GET /eval/results — 获取最新 eval 报告
- GET /eval/dataset — 查看 golden dataset 摘要
"""

from fastapi import APIRouter

from backend.services.eval_runner import eval_runner

router = APIRouter(prefix="/eval", tags=["eval"])


@router.post("/run")
async def run_eval():
    """触发全量 eval 运行"""
    report = eval_runner.run_all()
    return report.to_dict()


@router.get("/results")
async def get_eval_results():
    """获取最新 eval 报告"""
    report = eval_runner.get_last_report()
    if report is None:
        return {"message": "No eval results yet. Run POST /eval/run first."}
    return report


@router.get("/dataset")
async def get_dataset_summary():
    """查看 golden dataset 摘要"""
    return eval_runner.get_dataset_summary()
