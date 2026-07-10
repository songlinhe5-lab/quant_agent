import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { Toaster } from '@/components/ui/toaster'
import { ConfirmDialogProvider } from '@/components/confirm-dialog'
import { ProtectedRoute } from '@/components/layout/protected-route'
import DashboardLayout from '@/components/layout/dashboard-layout'
import LoginPage from '@/features/auth/login'

// 懒加载各功能模块（按需加载，减少首屏体积）
import { lazy, Suspense } from 'react'

const DataCenterModule = lazy(() => import('@/features/trading/data-center').then(m => ({ default: m.DataCenterModule })))
const QuotesModule = lazy(() => import('@/features/trading/quotes').then(m => ({ default: m.QuotesModule })))
const ScreenerModule = lazy(() => import('@/features/trading/screener').then(m => ({ default: m.ScreenerModule })))
const StrategyDevModule = lazy(() => import('@/features/trading/strategy').then(m => ({ default: m.StrategyDevModule })))
const BacktestModule = lazy(() => import('@/features/trading/backtest').then(m => ({ default: m.BacktestModule })))
const OMSModule = lazy(() => import('@/features/trading/oms').then(m => ({ default: m.OMSModule })))
const RiskModule = lazy(() => import('@/features/trading/risk').then(m => ({ default: m.RiskModule })))
const CopilotModule = lazy(() => import('@/features/trading/copilot').then(m => ({ default: m.CopilotModule })))
const ApmModule = lazy(() => import('@/features/system/performance-panel').then(m => ({ default: m.PerformancePanel })))
const SettingsPage = lazy(() => import('@/features/settings/settings'))

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
            <Route path="/data-center" element={<Suspense fallback={<LoadingFallback />}><DataCenterModule /></Suspense>} />
            <Route path="/quotes" element={<Suspense fallback={<LoadingFallback />}><QuotesModule /></Suspense>} />
            <Route path="/screener" element={<Suspense fallback={<LoadingFallback />}><ScreenerModule /></Suspense>} />
            <Route path="/strategy" element={<Suspense fallback={<LoadingFallback />}><StrategyDevModule /></Suspense>} />
            <Route path="/backtest" element={<Suspense fallback={<LoadingFallback />}><BacktestModule /></Suspense>} />
            <Route path="/oms" element={<Suspense fallback={<LoadingFallback />}><OMSModule /></Suspense>} />
            <Route path="/risk" element={<Suspense fallback={<LoadingFallback />}><RiskModule /></Suspense>} />
            <Route path="/copilot" element={<Suspense fallback={<LoadingFallback />}><CopilotModule /></Suspense>} />
            <Route path="/apm" element={<Suspense fallback={<LoadingFallback />}><ApmModule /></Suspense>} />
            <Route path="/settings" element={<Suspense fallback={<LoadingFallback />}><SettingsPage /></Suspense>} />
            </Route>
          </Route>
        </Routes>

        {/* 全局 Toast 通知 */}
        <Toaster />
      </ConfirmDialogProvider>
    </>
  )
}
