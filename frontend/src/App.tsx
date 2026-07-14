import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { Toaster } from '@/components/ui/toaster'
import { ConfirmDialogProvider } from '@/components/confirm-dialog'
import { ProtectedRoute } from '@/components/layout/protected-route'
import DashboardLayout from '@/components/layout/dashboard-layout'
import LoginPage from '@/features/auth/login'
import { ModuleErrorBoundary } from '@/components/error-boundary'

// 懒加载各功能模块（按需加载，减少首屏体积）
import { lazy, Suspense, type ComponentType } from 'react'

/**
 * 带错误处理的 lazy loader
 * 捕获 chunk 加载失败（如 404、网络错误），重新抛出以便 ErrorBoundary 捕获
 */
function lazyWithRetry<T extends ComponentType<any>>(
  importFn: () => Promise<{ default: T }>,
): ComponentType<any> {
  return lazy(() =>
    importFn().catch((err) => {
      // ChunkLoadError 或网络错误时，重新抛出以便 ErrorBoundary 显示错误页面
      throw new Error(`模块加载失败：${err.message || '未知错误'}`)
    }),
  )
}

const DataCenterModule = lazyWithRetry(() => import('@/features/trading/data-center').then(m => ({ default: m.DataCenterModule })))
const QuotesModule = lazyWithRetry(() => import('@/features/trading/quotes').then(m => ({ default: m.QuotesModule })))
const ScreenerModule = lazyWithRetry(() => import('@/features/trading/screener').then(m => ({ default: m.ScreenerModule })))
const StrategyDevModule = lazyWithRetry(() => import('@/features/trading/strategy').then(m => ({ default: m.StrategyDevModule })))
const BacktestModule = lazyWithRetry(() => import('@/features/trading/backtest').then(m => ({ default: m.BacktestModule })))
const OMSModule = lazyWithRetry(() => import('@/features/trading/oms').then(m => ({ default: m.OMSModule })))
const RiskModule = lazyWithRetry(() => import('@/features/trading/risk').then(m => ({ default: m.RiskModule })))
const CopilotModule = lazyWithRetry(() => import('@/features/trading/copilot').then(m => ({ default: m.CopilotModule })))
const ApmModule = lazyWithRetry(() => import('@/features/system/performance-panel').then(m => ({ default: m.PerformancePanel })))
const AlertCenterModule = lazyWithRetry(() => import('@/features/trading/alert-center').then(m => ({ default: m.AlertCenterModule })))
const PaperModule = lazyWithRetry(() => import('@/features/paper/module').then(m => ({ default: m.PaperModule })))
const SettingsPage = lazyWithRetry(() => import('@/features/settings/settings'))

// /market/:ticker 跳转组件：将 URL 中的 ticker 存入 sessionStorage，然后重定向到 /quotes
function MarketTickerRedirect() {
  const { ticker } = useParams<{ ticker: string }>()
  // 同步设置 sessionStorage（在 render 阶段，确保 <Navigate> 触发前已写入）
  if (ticker) {
    sessionStorage.setItem('quant_target_symbol', decodeURIComponent(ticker))
  }
  return <Navigate to="/quotes" replace />
}

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center h-full w-full bg-background/50 backdrop-blur-sm">
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <p className="text-xs text-muted-foreground font-mono">Loading Module...</p>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <>
      <ConfirmDialogProvider>
        <Routes>
          {/* 登录页（无布局） */}
          <Route path="/login" element={<LoginPage />} />

          {/* 主应用布局（带认证保护） */}
          <Route element={<ProtectedRoute />}>
            <Route element={<DashboardLayout />}>
            <Route index element={<Navigate to="/data-center" replace />} />
            <Route path="/market/:ticker" element={<MarketTickerRedirect />} />
            <Route path="/data-center" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="DataCenter"><DataCenterModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/quotes" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="Quotes"><QuotesModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/screener" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="Screener"><ScreenerModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/strategy" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="Strategy"><StrategyDevModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/backtest" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="Backtest"><BacktestModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/oms" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="OMS"><OMSModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/risk" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="Risk"><RiskModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/copilot" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="Copilot"><CopilotModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/apm" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="APM"><ApmModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/alerts" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="Alerts"><AlertCenterModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/paper" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="Paper"><PaperModule /></ModuleErrorBoundary></Suspense>} />
            <Route path="/settings" element={<Suspense fallback={<LoadingFallback />}><ModuleErrorBoundary name="Settings"><SettingsPage /></ModuleErrorBoundary></Suspense>} />
            </Route>
          </Route>
        </Routes>

        {/* 全局 Toast 通知 */}
        <Toaster />
      </ConfirmDialogProvider>
    </>
  )
}
