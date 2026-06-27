import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from '@/components/ui/toaster'
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
// TODO: 创建 @/features/system/apm 模块
// const ApmPanel = lazy(() => import('@/features/system/apm').then(m => ({ default: m.ApmPanel })))
const SettingsPage = lazy(() => import('@/features/settings/settings'))

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
      <BrowserRouter>
        <Routes>
          {/* 登录页（无布局） */}
          <Route path="/login" element={<LoginPage />} />

          {/* 主应用布局（带认证保护） */}
          {/* TODO: 修复 ProtectedRoute children prop 类型错误
          <Route element={<ProtectedRoute children={<DashboardLayout />} />}>
          */}
          {/* 临时：不使用认证保护 */}
          <Route element={<DashboardLayout />}>
            <Route index element={<Navigate to="/data-center" replace />} />
            <Route path="/data-center" element={<Suspense fallback={<LoadingFallback />}><DataCenterModule /></Suspense>} />
            <Route path="/quotes" element={<Suspense fallback={<LoadingFallback />}><QuotesModule /></Suspense>} />
            <Route path="/screener" element={<Suspense fallback={<LoadingFallback />}><ScreenerModule /></Suspense>} />
            <Route path="/strategy" element={<Suspense fallback={<LoadingFallback />}><StrategyDevModule /></Suspense>} />
            <Route path="/backtest" element={<Suspense fallback={<LoadingFallback />}><BacktestModule /></Suspense>} />
            <Route path="/oms" element={<Suspense fallback={<LoadingFallback />}><OMSModule /></Suspense>} />
            <Route path="/risk" element={<Suspense fallback={<LoadingFallback />}><RiskModule /></Suspense>} />
            <Route path="/copilot" element={<Suspense fallback={<LoadingFallback />}><CopilotModule /></Suspense>} />
            {/* TODO: 启用 APM 路由 after creating @/features/system/apm module */}
            {/* <Route path="/apm" element={<Suspense fallback={<LoadingFallback />}><ApmPanel /></Suspense>} /> */}
            <Route path="/settings" element={<Suspense fallback={<LoadingFallback />}><SettingsPage /></Suspense>} />
          </Route>
        </Routes>
      </BrowserRouter>

      {/* 全局 Toast 通知 */}
      <Toaster />
    </>
  )
}
