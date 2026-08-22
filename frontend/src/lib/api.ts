/**
 * Prompt Governance API Client
 */

export async function fetchPromptDashboard(): Promise<DashboardResponse[]> {
  const response = await fetch("/api/prompt-governance/dashboard");
  if (!response.ok) throw new Error("Failed to fetch dashboard");
  return response.json();
}

export async function fetchVersionHistory(promptName: string): Promise<VersionHistoryResponse> {
  const response = await fetch(`/api/prompt-governance/versions/${promptName}/history`);
  if (!response.ok) throw new Error("Failed to fetch versions");
  return response.json();
}

export async function recordFeedback(data: FeedbackRequest): Promise<{ status: string }> {
  const response = await fetch("/api/prompt-governance/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error("Failed to record feedback");
  return response.json();
}

export interface DashboardResponse {
  prompt_name: string;
  current_version: string;
  quality_score: number;
  trend_7d: Array<{ ts: number; score: number }>;
  ab_tests: Array<ABTestResult>;
  feedback_stats: FeedbackStats;
  version_count: number;
  last_updated: number;
}

export interface ABTestResult {
  name: string;
  status: "running" | "completed" | "cancelled";
  winner_variant?: string;
  improvement: number;
  traffic_split?: { v1: number; v2: number };
}

export interface FeedbackStats {
  up_ratio: number;
  avg_rating: number;
  total_count: number;
  down_ratio?: number;
}

export interface VersionHistoryResponse {
  name: string;
  current_version: string;
  versions: Array<{
    version: string;
    checksum: string;
    created_at: number;
    metadata: Record<string, any>;
  }>;
}

export interface FeedbackRequest {
  prompt_name: string;
  version: string;
  user_id: string;
  rating: -1 | 0 | 1;
  comment?: string;
}

// ============= Prompt Approval Types =============
export interface PendingApprovalResponse {
  id: string;
  prompt_name: string;
  from_version: string;
  to_version: string;
  quality_score_at_approval: number;
  created_at: string;
  reviewer_username?: string;
}

export interface ApprovalHistoryResponse {
  id: string;
  status: "pending" | "approved" | "rejected" | "rolled_back";
  reviewer_user_id?: string;
  reviewer_username?: string;
  approved_at?: string;
  rejected_at?: string;
  deployed_to_production: boolean;
  deployed_to_production_at?: string;
}
