/**
 * React Router 配置
 * 基于 ADR-001 (Pure Vite SPA)，使用模块切换模式而非页面路由
 */

import { createBrowserRouter, Navigate } from 'react-router-dom';
import { TradingDashboard } from '@/components/layout/trading-dashboard';
import LoginPage from '@/features/auth/login';
import { ProtectedRoute } from '@/components/layout/protected-route';

/**
 * 路由配置说明：
 * 
 * 1. 使用 TradingDashboard 作为主布局（模块切换模式）
 * 2. 所有功能模块作为 TradingDashboard 的子组件
 * 3. 通过 URL 参数 ?module=xxx 或 hash #xxx 来标识当前模块
 * 4. 不使用 React Router 的页面路由，避免组件卸载导致状态丢失
 * 
 * 参考：docs/04. 前端架构与零GC渲染.md §二
 */

const router = createBrowserRouter([
  {
    path: '/',
    element: <ProtectedRoute />,
    children: [
      {
        path: '',
        element: <TradingDashboard />,
        // 所有模块在 TradingDashboard 内部通过 state 切换
        // 不需要在这里配置子路由
      },
    ],
  },
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
]);

export default router;
