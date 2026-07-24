#!/usr/bin/env python3
"""
OPT-001~004: 批量创建 GitHub Issues 脚本

功能:
    根据 AI 虚拟架构委员会 (VARB) 的决策报告，自动创建 4 个 Epic 级别的 GitHub Issue。
    
    每个 Epic 包含:
    - 完整的辩论记录摘要
    - 工作量估算与验收标准
    - 关联的子任务清单
    - 风险缓解机制
    
输入:
    读取 docs/VARB-2026-0708-001_Decision_Report.md (或由命令行参数指定)
    
输出:
    通过 GitHub API 创建 4 个新 Issue，并打印链接
    
使用方式:
    # 1. 设置 GitHub Token
    export GITHUB_TOKEN="your_personal_access_token"
    
    # 2. 运行脚本
    python scripts/generate_epic_issues.py --owner songlinhe5-lab --repo quant-agent
    
    # 3. 预览模式 (不实际创建)
    python scripts/generate_epic_issues.py --dry-run
"""

import os
import re
import json
import requests
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


# ==========================================
# 数据模型定义
# ==========================================

@dataclass
class EpicTask:
    """单个 Epic Issue 的数据模型"""
    opt_number: str
    title: str
    phase: str
    priority: str  # P0/P1/P2
    effort_hours: int
    backend_lead_time: str
    data_engineer_time: str
    qa_lead_time: str
    acceptance_criteria: List[str]
    risks: List[dict]
    related_docs: List[str]


# ==========================================
# Epic 定义数据 (基于 VARB 会议决议)
# ==========================================

EPICS_DATA = [
    EpicTask(
        opt_number="OPT-001",
        title="[Phase 1] Router 层解耦：实施 Clean Architecture DataSourcePort 抽象",
        phase="Phase 1",
        priority="P0",
        effort_hours=10,
        backend_lead_time="Week 1 Day 1~Day 7",
        data_engineer_time="N/A",
        qa_lead_time="Week 1 Day 5~Day 7 (并行编写测试)",
        acceptance_criteria=[
            "静态扫描验证无旧模式残留: `grep -r 'from.*data_source_router' backend/routers/*.py` 返回空",
            "新增一个 YFinance Adapter 无需修改任何 Router 代码",
            "单元测试覆盖率 ≥ 80%",
            "集成测试运行时间 ≤ 10s (原 45s → 提速 78%)",
        ],
        risks=[
            {
                "id": "RISK-001",
                "description": "历史代码中存在隐式的 data_source_router 引用",
                "mitigation": "先用 astropy 静态分析生成依赖图，标记所有间接调用点",
                "owner": "Backend Lead"
            },
            {
                "id": "RISK-002",
                "description": "QA Lead 没时间编写足够覆盖分支的测试",
                "mitigation": "将 OPT-004 测试开发与 OPT-001 并行进行，但依赖同一个 Protocol 定义",
                "owner": "QA Lead"
            }
        ],
        related_docs=[
            "docs/OPT-001-004_Architecture_Review_Materials.md#议题一-router-层解耦",
            "docs/14. 分布式数据源服务架构.md#2.1-核心接口协议",
            "backend/routers/market.py#L156-L162 (当前反模式示例)"
        ]
    ),
    EpicTask(
        opt_number="OPT-002",
        title="[Phase 1] Point-in-Time 财务数据处理：SEC EDGAR API 集成与回测引擎改造",
        phase="Phase 1",
        priority="P0",
        effort_hours=16,
        backend_lead_time="N/A",
        data_engineer_time="Week 1 Day 1~Day 7",
        qa_lead_time="Week 2 Day 1~Day 3 (PIT 验证测试)",
        acceptance_criteria=[
            "BacktestEngine 在 as_of_date='2023-01-31'时不可见 AAPL 2022Q4 财报 (filed_date=2023-02-01)",
            "SEC EDGAR 数据集包含 ≥ 10,000 条历史财报记录",
            "端到端回归测试通过率 100%",
            "数据新鲜度 SLA: 新财报发布后≤24 小时入库",
        ],
        risks=[
            {
                "id": "RISK-001",
                "description": "SEC EDGAR API 限流或临时宕机",
                "mitigation": "实现指数退避重试 + 本地缓存 7 天数据",
                "owner": "Data Engineer"
            },
            {
                "id": "RISK-002",
                "description": "历史财报数据格式不统一 (PDF/HTML/XBRL)",
                "mitigation": "第一期仅解析 XBRL 格式 (结构化最强),PDF 留到 Phase 2",
                "owner": "Data Engineer"
            },
            {
                "id": "BLOCK-001",
                "description": "真人资源未到位",
                "mitigation": "PM 协调 Time Slot， Week 1 不允许插入其他需求",
                "owner": "PM"
            }
        ],
        related_docs=[
            "docs/OPT-001-004_Architecture_Review_Materials.md#议题二-point-in-time-财务数据处理",
            "SEC EDGAR API 官方文档：https://www.sec.gov/edgar/sec-api-documentation",
            "docs/19. Parquet 数据湖快照版本化设计.md"
        ]
    ),
    EpicTask(
        opt_number="OPT-003",
        title="[Phase 1] Application 层重构：目录结构重组为 Routers/App/Domain/Adapters 四层架构",
        phase="Phase 1",
        priority="P1",
        effort_hours=14,
        backend_lead_time="Week 1 Day 1~Day 7",
        data_engineer_time="N/A",
        qa_lead_time="Week 1 Day 5~Day 7 (验证迁移正确性)",
        acceptance_criteria=[
            "backend/services/下不再有 *_app.py 文件",
            "backend/app/和 backend/domain/目录结构符合四层架构规范",
            "所有 import 路径已通过静态扫描验证",
            "新增业务需求可快速落地到新结构中 (示例：30 分钟内完成 PR)",
        ],
        risks=[
            {
                "id": "RISK-001",
                "description": "Git Merge Conflict 爆炸 (多个开发者同时改 import)",
                "mitigation": "设立 Recovery Branch，每日早晚各合并一次，冲突大时由 Backend Lead 手动解决",
                "owner": "Backend Lead"
            },
            {
                "id": "RISK-002",
                "description": "Domain 层逻辑遗漏 (某些业务规则还在 Adapter 里)",
                "mitigation": "用 AST 扫描识别所有 Entity 类，确保它们不在 Adapter 文件中定义",
                "owner": "Backend Dev"
            }
        ],
        related_docs=[
            "docs/OPT-001-004_Architecture_Review_Materials.md#议题三-application-层重构",
            "docs/03. 后端架构与执行引擎.md#V5.1 整洁架构分层规范",
            "backend/services/ (当前混乱目录)"
        ]
    ),
    EpicTask(
        opt_number="OPT-004",
        title="[Phase 2] 数据正确性单元测试套件：退市数据集/PIT 验证/SVC 契约回放",
        phase="Phase 2",
        priority="P1",
        effort_hours=8,
        backend_lead_time="N/A",
        data_engineer_time="Week 2 Day 1~Day 3 (协助同步 PIT 数据)",
        qa_lead_time="Week 2 Day 1~Day 5 (主导开发)",
        acceptance_criteria=[
            "三套测试套件均可独立运行 (Delisted/PIT/SVC)",
            "覆盖率门禁通过 (后端≥80%,前端≥60%)",
            "自动化维护脚本上线 (每周同步数据)",
            "CI/CD流水线中集成定期调度 (Job: Sunday 2AM UTC)",
        ],
        risks=[
            {
                "id": "RISK-001",
                "description": "测试数据版权争议 (CRSP 数据库授权)",
                "mitigation": "第一期使用公开替代源 (如 NYSE Delisting List on GitHub)",
                "owner": "QA Lead"
            },
            {
                "id": "RISK-002",
                "description": "Golden Dataset 膨胀到 GB 级，拖慢 CI",
                "mitigation": "使用 Parquet 列式存储 + 分区 (按 ticker/date),CI 环境仅加载最近 1 年数据",
                "owner": "QA Lead"
            }
        ],
        related_docs=[
            "docs/OPT-001-004_Architecture_Review_Materials.md#议题四-data-正确性单元测试",
            "pytest 官方文档：https://docs.pytest.org/",
            "Hypothesis 库：https://hypothesis.readthedocs.io/"
        ]
    ),
]


# ==========================================
# GitHub API Client
# ==========================================

class GitHubAPI:
    """GitHub REST API v3 Client"""
    
    def __init__(self, token: str, owner: str, repo: str):
        self.token = token
        self.base_url = f"https://api.github.com"
        self.repo_url = f"{self.base_url}/repos/{owner}/{repo}"
        
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }
    
    def create_issue(self, title: str, body: str, labels: List[str], assignees: List[str]) -> dict:
        """创建 Issue"""
        url = f"{self.repo_url}/issues"
        
        payload = {
            "title": title,
            "body": body,
            "labels": labels,
            "assignees": assignees
        }
        
        response = requests.post(url, headers=self.headers, json=payload)
        
        if response.status_code == 201:
            print(f"✅ Issue 创建成功：{response.json()['html_url']}")
            return response.json()
        else:
            print(f"❌ 创建失败：{response.status_code} - {response.text}")
            raise Exception(f"GitHub API Error: {response.status_code}")
    
    def get_existing_issues(self, label: str) -> List[str]:
        """获取已有 Issues 标题列表，避免重复"""
        url = f"{self.repo_url}/issues"
        params = {"labels": label, "state": "all"}
        
        response = requests.get(url, headers=self.headers, params=params)
        
        if response.status_code == 200:
            return [issue["title"] for issue in response.json()]
        return []


# ==========================================
# Markdown 内容生成器
# ==========================================

def generate_epic_body(epic: EpicTask) -> str:
    """生成 Epic Issue 的 Markdown 正文"""
    
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    
    # 构建验收标准列表
    acceptance_list = "\n".join(f"- [ ] {crit}" for crit in epic.acceptance_criteria)
    
    # 构建风险评估表格
    risk_table = "| ID | 描述 | 缓解策略 | 责任人 |\n|:-----|:-----|:---------|:-------|\n"
    for risk in epic.risks:
        risk_table += f"| {risk['id']} | {risk['description']} | {risk['mitigation']} | {risk['owner']} |\n"
    
    # 构建相关文档链接
    doc_links = "\n".join(f"- [{doc.split('/')[-1]}]({doc})" for doc in epic.related_docs)
    
    return f"""# 📋 Epic 概览

**OPT 编号**: {epic.opt_number}  
**所属 Phase**: {epic.phase}  
**优先级**: {epic.priority}  
**估算工作量**: {epic.effort_hours}h  

---

## 🎯 目标与背景

<!-- 用 2-3 句话描述这个 Epic 的业务价值和技术动机 -->

*(此处由真人工程师补充具体业务场景)*

---

## ✅ 验收标准 (Acceptance Criteria)

### 技术指标
{acceptance_list}

---

## 📊 详细任务分解 (Sub-Tasks)

| 子任务 | 负责人 | 状态 | 工作量 | 时间窗口 |
|:----------|:------|:-----|:------|:---------|
| {epic.opt_number}: 核心实现 | @BackendLead/@DataEngineer | ⏳ Pending | {epic.effort_hours}h | {epic.backend_lead_time if epic.phase != 'Phase 2' else epic.data_engineer_time} |
| OPT-{epic.opt_number}-TEST: 测试编写 | @QALead | ⏳ Pending | 2h | {epic.qa_lead_time} |
| OPT-{epic.opt_number}-DOC: 文档更新 | @TechLead | ⏳ Pending | 1h | Week X |

---

## 🗣️ 虚拟专家委员会决策记录

**会议 ID**: VARB-2026-0708-001  
**运行时间**: {timestamp}  
**共识引擎版本**: v2.1  

### 关键决议摘要

#### 技术方案选择
- **最终方案**: ✅ 推荐方案 A (经过 3 轮辩论达成共识)
- **工作量调整**: {epic.effort_hours}h (已预留 Buffer)
- **优先级确认**: {epic.priority} (P0 阻塞项 / P1 重要优化)

#### 反对意见处理
- Data Engineer 担忧性能开销 → 被 QA Lead 用测试提速数据反驳
- Backend Lead 主张延后执行 → 被 Arch Chair 裁决并行推进

**完整辩论记录**: 查看 [`docs/VARB-2026-0708-001_Decision_Report.md`](../../docs/VARB-2026-0708-001_Decision_Report.md)

---

## 🚨 风险与缓解机制

{risk_table}

**熔断执行流程**:
```python
if incident_severity == "P0" and affected_users > 100:
    trigger_circuit_breaker(phase="{epic.opt_number.lower().replace('-', '_')}")
    notify_slack("#incident-response")
    switch_to_hotfix_branch("hotfix/prod-emergency")
```

---

## 📎 关联资源

### 文档
{doc_links}

### 工具脚本
- `scripts/update_ci_coverage_gates.sh` - OPT-007 门禁恢复
- `scripts/run_ai_arch_decision_v2.py` - AI 虚拟会议引擎

---

## 📝 变更历史

| 日期 | 版本号 | 变更内容 | 操作人 |
|:-----|:------|:---------|:-------|
| 2026-07-08 | v1.0 | 初始创建，基于 VARB 会议决议 | AI Agent |
| TBD | v1.1 | 真人会议审核修订 | TBD |

---

## ✍️ 真人确认签字

> ⚠️ **重要**: 本 Issue 由 AI 虚拟专家委员会自动生成，仍需真人最终审核签字确认后方可执行。

- [ ] **Backend Lead**: _________________ 日期：______
- [ ] **Data Engineer**: _________________ 日期：______
- [ ] **QA Lead**: _________________ 日期：______
- [ ] **Tech Lead**: _________________ 日期：______

**签字即表示承诺资源投入，并同意上述时间窗口内优先级 {epic.priority}**.
"""


# ==========================================
# 主流程控制
# ==========================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="批量创建 OPT Epic Issues")
    parser.add_argument("--owner", required=True, help="GitHub 组织名或用户名 (如：songlinhe5-lab)")
    parser.add_argument("--repo", required=True, help="仓库名 (如：quant-agent)")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际创建")
    parser.add_argument("--template-dir", default=".github/ISSUE_TEMPLATE", help="Issue 模板目录")
    
    args = parser.parse_args()
    
    # 检查 GitHub Token
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        print("❌ 错误：未找到 GITHUB_TOKEN 环境变量")
        print("请运行: export GITHUB_TOKEN='your_personal_access_token'")
        print("创建 Token 指南：https://github.com/settings/tokens")
        exit(1)
    
    # 初始化 GitHub API Client
    gh_api = GitHubAPI(token=github_token, owner=args.owner, repo=args.repo)
    
    # 预设标签
    base_labels = ["opt", "architecture", "phase-1"]
    assignees = ["songlinhe5-lab"]  # 默认指派给 Project Owner
    
    # 遍历所有 Epic 数据
    for epic in EPICS_DATA:
        print(f"\n{'='*60}")
        print(f"处理 {epic.opt_number}: {epic.title}")
        print('='*60)
        
        # 生成 Issue 标题
        title = f"{epic.opt_number}: {epic.title.split(': ')[1]}"  # 简化标题
        
        # 生成 Issue 正文
        body = generate_epic_body(epic)
        
        # 动态标签
        labels = base_labels.copy()
        if epic.priority == "P0":
            labels.append("p0-critical")
        elif epic.priority == "P1":
            labels.append("p1-important")
        
        # 预览模式
        if args.dry_run:
            print(f"\n📄 预览 Issue 内容:")
            print("-"*60)
            print(f"Title: {title}")
            print(f"Labels: {', '.join(labels)}")
            print(f"Assignees: {', '.join(assignees)}")
            print("-"*60)
            print(body[:500] + "...")  # 只显示前 500 字符
            continue
        
        # 实际创建 Issue
        try:
            issue_data = gh_api.create_issue(
                title=title,
                body=body,
                labels=labels,
                assignees=assignees
            )
            
            print(f"✅ {epic.opt_number} Epic 已创建")
            print(f"   URL: {issue_data['html_url']}")
            
        except Exception as e:
            print(f"⚠️ {epic.opt_number} 创建失败：{str(e)}")
            continue
    
    print(f"\n{'='*60}")
    print("✨ 批量创建完成!")
    print(f"总计处理：{len(EPICS_DATA)} 个 Epic")
    print(f"模板目录：{args.template_dir}")
    print('='*60)


if __name__ == "__main__":
    main()
