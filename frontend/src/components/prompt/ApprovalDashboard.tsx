/**
 * Prompt Governance Approval Dashboard - Frontend Component
 * Human-in-the-loop 审批管理面板
 */

import { useState, useEffect } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { CheckCircle2, XCircle, Clock, RefreshCw, ArrowRightLeft, Eye } from "lucide-react";
import type { PendingApprovalResponse, ApprovalHistoryResponse } from "@/lib/api";

interface ApprovalDashboardProps {
  currentUser?: {
    id: string;
    username: string;
  };
}

export function ApprovalDashboard({ currentUser }: ApprovalDashboardProps) {
  const [pendingApprovals, setPendingApprovals] = useState<PendingApprovalResponse[]>([]);
  const [selectedPrompt, setSelectedPrompt] = useState<string>("all");
  const [loading, setLoading] = useState(true);

  // Modal states
  const [actionDialogOpen, setActionDialogOpen] = useState(false);
  const [selectedAuditId, setSelectedAuditId] = useState<string | null>(null);
  const [actionType, setActionType] = useState<"approve" | "reject" | "rollback" | null>(null);
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Deployment history
  const [deploymentHistory, setDeploymentHistory] = useState<any[]>([]);
  const [showDeployments, setShowDeployments] = useState(false);

  // Fetch pending approvals
  useEffect(() => {
    async function loadApprovals() {
      try {
        const response = await fetch("/api/prompt-governance/approval/pending?limit=50");
        if (response.ok) {
          const data = await response.json();
          setPendingApprovals(data);
        }
      } catch (error) {
        console.error("Failed to load approvals:", error);
      } finally {
        setLoading(false);
      }
    }

    loadApprovals();

    // Auto-refresh every 30 seconds
    const interval = setInterval(loadApprovals, 30000);
    return () => clearInterval(interval);
  }, []);

  // Handle approve action
  const handleApprove = async () => {
    if (!selectedAuditId || !currentUser) return;

    setSubmitting(true);
    try {
      const response = await fetch("/api/prompt-governance/approval/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audit_id: selectedAuditId,
          comment: comment || "Approved via dashboard",
          user_id: currentUser.id,
          username: currentUser.username,
        }),
      });

      if (response.ok) {
        setPendingApprovals((prev) => prev.filter(a => a.id !== selectedAuditId));
        alert("✅ Version approved successfully!");
      } else {
        const error = await response.json();
        alert(`❌ Failed: ${error.detail}`);
      }
    } catch (error) {
      console.error("Approval failed:", error);
      alert("Error approving version");
    } finally {
      setSubmitting(false);
      setActionDialogOpen(false);
      setComment("");
    }
  };

  // Handle reject action
  const handleReject = async () => {
    if (!selectedAuditId || !currentUser) return;

    setSubmitting(true);
    try {
      const response = await fetch("/api/prompt-governance/approval/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audit_id: selectedAuditId,
          reason: reason || "Rejected via dashboard",
          user_id: currentUser.id,
          username: currentUser.username,
        }),
      });

      if (response.ok) {
        setPendingApprovals((prev) => prev.filter(a => a.id !== selectedAuditId));
        alert("✅ Version rejected.");
      } else {
        const error = await response.json();
        alert(`❌ Failed: ${error.detail}`);
      }
    } catch (error) {
      console.error("Rejection failed:", error);
      alert("Error rejecting version");
    } finally {
      setSubmitting(false);
      setActionDialogOpen(false);
      setReason("");
    }
  };

  // Trigger rollback
  const handleRollback = async () => {
    if (!selectedAuditId || !currentUser) return;

    setSubmitting(true);
    try {
      // Get target version from approval record first
      const audit = pendingApprovals.find(a => a.id === selectedAuditId);
      if (!audit) throw new Error("Audit not found");

      const response = await fetch("/api/prompt-governance/approval/rollback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt_name: audit.prompt_name,
          target_version: audit.from_version,
          reason: reason || `Rolled back via dashboard`,
          user_id: currentUser.id,
          username: currentUser.username,
          deploy_environment: "production",
        }),
      });

      if (response.ok) {
        alert("✅ Rollback initiated successfully!");
      } else {
        const error = await response.json();
        alert(`❌ Failed: ${error.detail}`);
      }
    } catch (error) {
      console.error("Rollback failed:", error);
      alert("Error initiating rollback");
    } finally {
      setSubmitting(false);
      setActionDialogOpen(false);
      setReason("");
    }
  };

  // Load deployment history
  const loadDeploymentHistory = async (promptName: string) => {
    try {
      const response = await fetch(`/api/prompt-governance/approval/${promptName}/deployments?limit=20`);
      if (response.ok) {
        const data = await response.json();
        setDeploymentHistory(data);
        setShowDeployments(true);
      }
    } catch (error) {
      console.error("Failed to load deployments:", error);
    }
  };

  // Open action dialog
  const openActionDialog = (auditId: string, type: "approve" | "reject" | "rollback") => {
    setSelectedAuditId(auditId);
    setActionType(type);
    setActionDialogOpen(true);
    setComment("");
    setReason("");
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Prompt Approval Dashboard</h1>
          <p className="text-muted-foreground mt-2">
            Human-in-the-loop 审批流程管理 • 待审批：<Badge variant="secondary">{pendingApprovals.length}</Badge>
          </p>
        </div>

        <Button
          onClick={() => window.location.reload()}
          variant="outline"
          disabled={loading}
        >
          <RefreshCw className="h-4 w-4 mr-2" />
          刷新列表
        </Button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <StatCard
          title="待审批数量"
          value={pendingApprovals.length}
          icon={<Clock className="h-5 w-5 text-amber-500" />}
          color="amber"
        />

        <StatCard
          title="本月已批准"
          value={deploymentHistory.filter(d => d.status === "approved").length}
          icon={<CheckCircle2 className="h-5 w-5 text-emerald-500" />}
          color="emerald"
        />

        <StatCard
          title="本月已拒绝"
          value={deploymentHistory.filter(d => d.status === "rejected").length}
          icon={<XCircle className="h-5 w-5 text-red-500" />}
          color="red"
        />
      </div>

      {/* Action Bar */}
      <Card className="glass-panel">
        <CardContent className="pt-6">
          <div className="flex items-center space-x-4 mb-4">
            <Label htmlFor="prompt-filter">筛选 Prompt:</Label>
            <select
              id="prompt-filter"
              className="input input-sm w-auto"
              onChange={(e) => setSelectedPrompt(e.target.value)}
            >
              <option value="all">全部</option>
              {Array.from(new Set(pendingApprovals.map(a => a.prompt_name)))
                .sort()
                .map(name => (
                  <option key={name} value={name}>{name}</option>
                ))}
            </select>

            <span className="text-sm text-muted-foreground ml-auto">
              自动刷新间隔：30 秒
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Pending Approvals Table */}
      <Card className="glass-panel">
        <CardHeader>
          <CardTitle>待审批版本队列</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
            </div>
          ) : pendingApprovals.length === 0 ? (
            <div className="text-center text-muted-foreground py-12">
              <Clock className="h-12 w-12 mx-auto mb-4 opacity-20" />
              <p>暂无待审批版本</p>
              <p className="text-sm mt-2">所有版本均已处理完成 ✅</p>
            </div>
          ) : (
            <div className="rounded-md border">
              <table className="w-full">
                <thead className="bg-secondary">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">版本差异</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">质量评分</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">提交时间</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {pendingApprovals
                    .filter(a => selectedPrompt === "all" || a.prompt_name === selectedPrompt)
                    .map((approval) => (
                      <tr key={approval.id} className="hover:bg-secondary/50">
                        <td className="px-4 py-3">
                          <div className="flex items-center space-x-2">
                            <span className="font-semibold text-sm">{approval.prompt_name}</span>
                            <ArrowRightLeft className="h-3 w-3 text-muted-foreground" />
                            <span className="font-mono text-xs bg-secondary px-2 py-0.5 rounded">
                              v{approval.from_version} → v{approval.to_version}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant={approval.quality_score_at_approval >= 0.7 ? "default" : "destructive"}>
                            {(approval.quality_score_at_approval * 100).toFixed(0)}%
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-sm text-muted-foreground">
                          {new Date(approval.created_at).toLocaleString("zh-CN")}
                        </td>
                        <td className="px-4 py-3 text-right space-x-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openActionDialog(approval.id, "approve")}
                          >
                            ✅ 批准
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openActionDialog(approval.id, "reject")}
                          >
                            ❌ 拒绝
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => loadDeploymentHistory(approval.prompt_name)}
                          >
                            <Eye className="h-3 w-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openActionDialog(approval.id, "rollback")}
                          >
                            ↩️ 回滚
                          </Button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Action Dialog */}
      <Dialog open={actionDialogOpen} onOpenChange={setActionDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {actionType === "approve" && "批准新版本"}
              {actionType === "reject" && "拒绝版本"}
              {actionType === "rollback" && "执行回滚"}
            </DialogTitle>
            <DialogDescription>
              {actionType === "approve" && "确认批准此版本部署到生产环境？"}
              {actionType === "reject" && "请输入拒绝原因（必填）"}
              {actionType === "rollback" && "确认回滚到此版本？这将覆盖当前生产版本！"}
            </DialogDescription>
          </DialogHeader>

          {actionType === "reject" && (
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="reject-reason">拒绝原因 *</Label>
                <Textarea
                  id="reject-reason"
                  placeholder="例如：质量评分低于阈值，需要优化..."
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="min-h-[80px]"
                />
              </div>
            </div>
          )}

          {actionType === "approve" && (
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="approve-comment">批准备注（可选）</Label>
                <Input
                  id="approve-comment"
                  placeholder="例如：通过代码审查和质量门禁"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                />
              </div>
            </div>
          )}

          {actionType === "rollback" && (
            <Alert>
              <AlertTitle className="text-red-500">⚠️ 警告：此操作将覆盖生产环境!</AlertTitle>
              <AlertDescription>
                回滚操作不可逆，请确认目标版本为期望状态。
              </AlertDescription>
            </Alert>
          )}

          <DialogFooter>
            {actionType === "approve" && (
              <>
                <Button variant="outline" onClick={() => setActionDialogOpen(false)}>
                  取消
                </Button>
                <Button
                  onClick={handleApprove}
                  disabled={submitting}
                  className="bg-emerald-600 hover:bg-emerald-700"
                >
                  {submitting ? "批准中..." : "✅ 批准"}
                </Button>
              </>
            )}

            {actionType === "reject" && (
              <>
                <Button variant="outline" onClick={() => setActionDialogOpen(false)}>
                  取消
                </Button>
                <Button
                  onClick={handleReject}
                  disabled={submitting}
                  className="bg-red-600 hover:bg-red-700"
                >
                  {submitting ? "拒绝中..." : "❌ 拒绝"}
                </Button>
              </>
            )}

            {actionType === "rollback" && (
              <>
                <Button variant="outline" onClick={() => setActionDialogOpen(false)}>
                  取消
                </Button>
                <Button
                  onClick={handleRollback}
                  disabled={submitting}
                  className="bg-amber-600 hover:bg-amber-700"
                >
                  {submitting ? "回滚中..." : "↩️ 确认回滚"}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Deploy History Dialog */}
      <Dialog open={showDeployments} onOpenChange={setShowDeployments}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>部署历史记录</DialogTitle>
            <DialogDescription>
              查看所有最近的生产部署和回滚操作
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            {deploymentHistory.length === 0 ? (
              <div className="text-center text-muted-foreground py-8">
                暂无部署记录
              </div>
            ) : (
              deploymentHistory.map((deployment, i) => (
                <div key={i} className="border rounded-lg p-4 glass-panel-subtle">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-2">
                      <Badge variant={deployment.action_type === "rollback" ? "destructive" : "default"}>
                        {deployment.action_type}
                      </Badge>
                      <span className="text-sm font-semibold">
                        v{deployment.version_before || "none"} → v{deployment.version_after}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {new Date(deployment.created_at).toLocaleString("zh-CN")}
                    </span>
                  </div>

                  <div className="text-sm space-y-1">
                    <div>
                      <span className="text-muted-foreground">操作人:</span>{" "}
                      <span className="font-medium">{deployment.performed_by_username}</span>
                    </div>
                    {deployment.reason && (
                      <div>
                        <span className="text-muted-foreground">原因:</span>{" "}
                        <span>{deployment.reason}</span>
                      </div>
                    )}
                    <div className="text-xs text-muted-foreground">
                      环境：{deployment.environment} | 状态：{deployment.success ? "✅ 成功" : "❌ 失败"}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// StatCard Component
function StatCard({
  title,
  value,
  icon,
  color = "gray"
}: {
  title: string;
  value: number | string;
  icon: React.ReactNode;
  color?: string;
}) {
  return (
    <Card className="glass-panel">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className={`text-3xl font-bold text-${color}-500`}>{value}</div>
      </CardContent>
    </Card>
  );
}
