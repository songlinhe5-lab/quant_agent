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
 * 3. market/:ticker 也直接渲染 TradingDashboard，内部通过 useParams 读取 ticker 处理跳转
 * 4. 不使用页面级路由切换，避免组件卸载导致状态丢失
 */

const router = createBrowserRouter([
  {
    path: '/',
    element: <ProtectedRoute />,
    children: [
      {
        path: '',
        element: <TradingDashboard />,
      },
      {
        // 市场详情页：直接渲染 TradingDashboard，内部通过 useParams 读取 ticker
        path: 'market/:ticker',
        element: <TradingDashboard />,
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
