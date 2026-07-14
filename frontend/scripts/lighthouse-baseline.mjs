#!/usr/bin/env node
/**
 * FE-14: Lighthouse 基准测量（禁用动效）
 *
 * 用法：
 *   1. pnpm build && pnpm preview --host 127.0.0.1 --port 4173
 *   2. pnpm lighthouse:baseline
 *
 * 默认 desktop preset（交易终端主场景）。移动节流可用：
 *   LIGHTHOUSE_FORM_FACTOR=mobile pnpm lighthouse:baseline
 *
 * 目标：Performance ≥ 85（报告写入 .lighthouse/）
 */
import { spawnSync } from 'node:child_process'
import { mkdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const url = process.env.LIGHTHOUSE_URL ?? 'http://127.0.0.1:4173/login?lighthouse=1'
const formFactor = process.env.LIGHTHOUSE_FORM_FACTOR ?? 'desktop'
const outName = formFactor === 'mobile' ? 'baseline' : 'baseline-desktop'
const outDir = resolve(process.cwd(), '.lighthouse')
mkdirSync(outDir, { recursive: true })
const outPath = resolve(outDir, outName)

const args = [
  'lighthouse',
  url,
  ...(formFactor === 'desktop' ? ['--preset=desktop'] : []),
  '--only-categories=performance,accessibility',
  '--chrome-flags=--headless=new --no-sandbox --allow-insecure-localhost',
  '--output=json',
  '--output=html',
  `--output-path=${outPath}`,
]

const result = spawnSync('npx', ['--yes', 'lighthouse@13.4.0', ...args], {
  stdio: 'inherit',
  shell: true,
  env: { ...process.env, npm_config_devdir: undefined },
})

try {
  const report = JSON.parse(readFileSync(`${outPath}.report.json`, 'utf8'))
  const perf = Math.round((report.categories?.performance?.score ?? 0) * 100)
  const a11y = Math.round((report.categories?.accessibility?.score ?? 0) * 100)
  console.log(`\nFE-14 ${formFactor}: Performance=${perf} Accessibility=${a11y} (target Perf≥85)`)
  if (perf < 85) process.exit(1)
} catch {
  process.exit(result.status ?? 1)
}

process.exit(result.status ?? 0)
