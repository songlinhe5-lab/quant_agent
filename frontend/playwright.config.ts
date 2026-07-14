/**
 * Playwright E2E 测试配置 (TEST-15)
 *
 * 用法:
 *   # 安装 Playwright
 *   pnpm add -D @playwright/test
 *   npx playwright install chromium
 *
 *   # 运行 E2E 测试（需要前后端服务运行）
 *   npx playwright test
 *
 *   # 运行特定测试
 *   npx playwright test login
 *
 *   # 生成报告
 *   npx playwright show-report
 */

import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL || 'http://localhost:5173'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: false, // E2E 测试串行执行更稳定
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],
  timeout: 30_000, // 单测试超时 30s

  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // 模拟认证 token（绕过登录）
    storageState: undefined,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // 开发服务器（如果前端未运行则自动启动）
  webServer: process.env.CI
    ? undefined // CI 环境假设服务已运行
    : {
        command: 'pnpm dev',
        url: baseURL,
        reuseExistingServer: true,
        timeout: 30_000,
      },
})
