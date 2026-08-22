/**
 * Prompt Governance Dashboard - Frontend Component
 * 可视化各版本的质量趋势、A/B 测试结果和反馈统计
 */

import { useState, useEffect } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AlertCircle, CheckCircle2, XCircle, TrendingUp, Search, ArrowUpDown } from "lucide-react";
import {
  fetchPromptDashboard,
  fetchVersionHistory,
  type DashboardResponse,
  type VersionHistoryResponse,
} from "@/lib/api";

export function PromptGovernanceDashboard() {
  const [selectedPrompt, setSelectedPrompt] = useState<string>("compact_summary_system_prompt");
  const [dashboardData, setDashboardData] = useState<DashboardResponse[]>([]);
  const [versionHistory, setVersionHistory] = useState<VersionHistoryResponse | null>(null);
  const [loadingDashboard, setLoadingDashboard] = useState(true);
  const [loadingVersions, setLoadingVersions] = useState(false);
  
  // Fetch dashboard metrics on mount
  useEffect(() => {
    async function loadDashboard() {
      try {
        const data = await fetchPromptDashboard();
        setDashboardData(data);
      } catch (error) {
        console.error("Failed to load dashboard:", error);
      } finally {
        setLoadingDashboard(false);
      }
    }
    
    loadDashboard();
  }, []);
  
  // Fetch version history when prompt changes
  useEffect(() => {
    async function loadVersions() {
      if (!selectedPrompt) return;
      
      setLoadingVersions(true);
      try {
        const data = await fetchVersionHistory(selectedPrompt);
        setVersionHistory(data);
      } catch (error) {
        console.error("Failed to load versions:", error);
      } finally {
        setLoadingVersions(false);
      }
    }
    
    loadVersions();
  }, [selectedPrompt]);
  
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Prompt Governance Dashboard</h1>
          <p className="text-muted-foreground mt-2">
            可视化 Prompt 版本质量趋势、A/B 测试结果和用户反馈
          </p>
        </div>
        
        {/* Prompt Selector */}
        <select
          className="input input-bordered w-full max-w-xs"
          value={selectedPrompt}
          onChange={(e) => setSelectedPrompt(e.target.value)}
        >
          {dashboardData?.map((item) => (
            <option key={item.prompt_name} value={item.prompt_name}>
              {item.prompt_name}
            </option>
          ))}
        </select>
      </div>
      
      {/* Main Dashboard Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Quality Score */}
        <QualityScoreCard 
          data={dashboardData?.find(d => d.prompt_name === selectedPrompt)} 
        />
        
        {/* Feedback Stats */}
        <FeedbackStatsCard 
          data={dashboardData?.find(d => d.prompt_name === selectedPrompt)} 
        />
        
        {/* Version Count */}
        <VersionCountCard 
          data={dashboardData?.find(d => d.prompt_name === selectedPrompt)} 
        />
        
        {/* Trend Analysis */}
        <TrendCard 
          data={dashboardData?.find(d => d.prompt_name === selectedPrompt)} 
        />
      </div>
      
      {/* Tabs for Detailed Views */}
      <Tabs defaultValue="versions" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="versions">版本历史</TabsTrigger>
          <TabsTrigger value="ab-tests">A/B 测试</TabsTrigger>
          <TabsTrigger value="feedback">用户反馈</TabsTrigger>
        </TabsList>
        
        <TabsContent value="versions">
          <VersionHistoryTable 
            data={versionHistory} 
            loading={loadingVersions} 
          />
        </TabsContent>
        
        <TabsContent value="ab-tests">
          <ABTestResultsPanel 
            data={dashboardData?.find(d => d.prompt_name === selectedPrompt)} 
          />
        </TabsContent>
        
        <TabsContent value="feedback">
          <FeedbackFeed 
            data={dashboardData?.find(d => d.prompt_name === selectedPrompt)} 
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// Quality Score Card
function QualityScoreCard({ data }: { data?: DashboardResponse }) {
  const score = data?.quality_score ?? 0;
  const trend = data?.trend_7d.length > 0 ? "up" : "neutral";
  
  const getScoreColor = (score: number) => {
    if (score >= 0.8) return "text-emerald-400";
    if (score >= 0.6) return "text-amber-400";
    return "text-red-400";
  };
  
  return (
    <Card className="glass-panel">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">综合质量评分</CardTitle>
        <TrendingUp className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className={`text-3xl font-bold ${getScoreColor(score)}`}>
          {(score * 100).toFixed(1)}%
        </div>
        <p className="text-xs text-muted-foreground mt-1">
          {trend === "up" ? "↗️ 趋势向上" : trend === "down" ? "↘️ 趋势向下" : "→ 保持稳定"}
        </p>
      </CardContent>
    </Card>
  );
}

// Feedback Stats Card
function FeedbackStatsCard({ data }: { data?: DashboardResponse }) {
  const stats = data?.feedback_stats ?? {};
  const upRatio = stats.up_ratio ?? 0;
  const avgRating = stats.avg_rating ?? 0;
  
  return (
    <Card className="glass-panel">
      <CardHeader>
        <CardTitle className="text-sm font-medium">用户反馈统计</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">点赞率</span>
          <Badge variant={upRatio > 0.7 ? "default" : "secondary"}>
            {(upRatio * 100).toFixed(0)}%
          </Badge>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">平均评分</span>
          <span className="text-sm font-semibold">{avgRating.toFixed(2)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">总反馈数</span>
          <span className="text-sm font-semibold">{stats.total_count ?? 0}</span>
        </div>
      </CardContent>
    </Card>
  );
}

// Version Count Card
function VersionCountCard({ data }: { data?: DashboardResponse }) {
  const count = data?.version_count ?? 0;
  
  return (
    <Card className="glass-panel">
      <CardHeader>
        <CardTitle className="text-sm font-medium">版本数量</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-bold text-primary">{count}</div>
        <p className="text-xs text-muted-foreground mt-1">
          当前版本：v{data?.current_version}
        </p>
      </CardContent>
    </Card>
  );
}

// Trend Card
function TrendCard({ data }: { data?: DashboardResponse }) {
  const trend = data?.trend_7d ?? [];
  
  return (
    <Card className="glass-panel">
      <CardHeader>
        <CardTitle className="text-sm font-medium">7 天质量趋势</CardTitle>
      </CardHeader>
      <CardContent>
        {trend.length > 0 ? (
          <div className="h-24 flex items-end space-x-1">
            {trend.slice(-7).map((point: { ts: number; score: number }, i: number) => (
              <div
                key={i}
                className="flex-1 bg-gradient-to-t from-primary to-primary/50 rounded-t"
                style={{ height: `${point.score * 100}%` }}
                title={`Day ${i + 1}: ${(point.score * 100).toFixed(1)}%`}
              />
            ))}
          </div>
        ) : (
          <div className="h-24 flex items-center justify-center text-muted-foreground text-sm">
            暂无数据
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Version History Table
function VersionHistoryTable({ data, loading }: { data?: VersionHistoryResponse; loading: boolean }) {
  if (loading) {
    return (
      <Card className="glass-panel">
        <CardContent className="pt-6">
          <div className="flex items-center justify-center h-32">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
          </div>
        </CardContent>
      </Card>
    );
  }
  
  if (!data) {
    return (
      <Card className="glass-panel">
        <CardContent className="pt-6 text-center text-muted-foreground">
          请先选择 Prompt
        </CardContent>
      </Card>
    );
  }
  
  return (
    <Card className="glass-panel">
      <CardHeader>
        <CardTitle>版本历史</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="rounded-md border">
          <table className="w-full">
            <thead className="bg-secondary">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">版本</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Checksum</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">创建时间</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">作者</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {[...data.versions].reverse().map((version, i) => (
                <tr key={version.version} className="hover:bg-secondary/50">
                  <td className="px-4 py-3 text-sm font-semibold">
                    {version.version}
                    {i === 0 && (
                      <Badge variant="outline" className="ml-2 text-xs">当前</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-muted-foreground">
                    {version.checksum}
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {new Date(version.created_at * 1000).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {version.metadata?.author || "-"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button variant="ghost" size="sm" className="text-xs">
                      查看
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// A/B Test Results Panel
function ABTestResultsPanel({ data }: { data?: DashboardResponse }) {
  const tests = data?.ab_tests ?? [];
  
  if (tests.length === 0) {
    return (
      <Card className="glass-panel">
        <CardContent className="pt-6 text-center text-muted-foreground">
          <Search className="h-12 w-12 mx-auto mb-4 opacity-20" />
          <p>暂无活跃 A/B 测试</p>
          <Button variant="outline" className="mt-4">
            创建新测试
          </Button>
        </CardContent>
      </Card>
    );
  }
  
  return (
    <Card className="glass-panel">
      <CardHeader>
        <CardTitle>A/B 测试结果</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {tests.map((test: any, i: number) => (
            <div key={i} className="border rounded-lg p-4 glass-panel-subtle">
              <div className="flex items-center justify-between mb-2">
                <h4 className="font-semibold">{test.name}</h4>
                <Badge variant={test.status === "completed" ? "default" : "secondary"}>
                  {test.status}
                </Badge>
              </div>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">Winner:</span>{" "}
                  <span className="font-semibold">{test.winner_variant || "-"}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Improvement:</span>{" "}
                  <span className="font-semibold text-emerald-400">
                    {(test.improvement * 100).toFixed(1)}%
                  </span>
                </div>
              </div>
              <div className="mt-3 flex items-center space-x-2 text-xs text-muted-foreground">
                <ArrowUpDown className="h-3 w-3" />
                <span>Traffic split: {test.traffic_split?.v1 || 50}% vs {test.traffic_split?.v2 || 50}%</span>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// Feedback Feed
function FeedbackFeed({ data }: { data?: DashboardResponse }) {
  const feedbacks = [
    { user: "alice", rating: 1, comment: "Great clarity and structure!", time: "2h ago" },
    { user: "bob", rating: 1, comment: "Excellent quality improvement", time: "5h ago" },
    { user: "charlie", rating: -1, comment: "Needs more specific constraints", time: "1d ago" },
  ];
  
  return (
    <Card className="glass-panel">
      <CardHeader>
        <CardTitle>用户反馈流</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {feedbacks.map((fb, i) => (
            <div key={i} className="flex items-start space-x-3 p-3 rounded-lg hover:bg-secondary/30 transition-colors">
              {fb.rating > 0 ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-400 mt-0.5" />
              ) : fb.rating < 0 ? (
                <XCircle className="h-5 w-5 text-red-400 mt-0.5" />
              ) : (
                <AlertCircle className="h-5 w-5 text-amber-400 mt-0.5" />
              )}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium">{fb.user}</span>
                  <span className="text-xs text-muted-foreground">{fb.time}</span>
                </div>
                <p className="text-sm text-muted-foreground">{fb.comment}</p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
