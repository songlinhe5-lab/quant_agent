'use client'

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import { apiClient } from '@/lib/api-client'
import { STORAGE_KEYS } from '@/lib/constants'

/**
 * AI-09：模块级 AI 推送偏好底座（前端复用层）。
 *
 * 取代散落在各功能卡片内的独立开关，AI-01~AI-08 的推送逻辑统一读此 store：
 *   - isEnabled(module) / thresholdOf(module) 供各模块运行时判断是否需要推送。
 *   - 本地 persist 兜底离线；fetch() 从后端拉取服务端权威配置并合并。
 *   - setPref() 即时写回后端（增量 PUT），保证多端一致。
 */

export type AiModule =
  | 'ai01'
  | 'ai02'
  | 'ai03'
  | 'ai04'
  | 'ai05'
  | 'ai06'
  | 'ai07'
  | 'ai08'

export interface AiPushPref {
  module: AiModule
  enabled: boolean
  threshold: number | null
}

/** 受控模块顺序（与后端 AI_PUSH_MODULES 一致） */
export const AI_PUSH_MODULES: AiModule[] = [
  'ai01',
  'ai02',
  'ai03',
  'ai04',
  'ai05',
  'ai06',
  'ai07',
  'ai08',
]

/** 模块中文释义，便于设置 UI 展示 */
export const AI_PUSH_MODULE_META: Record<AiModule, string> = {
  ai01: '异动解说员（K线浮动气泡）',
  ai02: '解盘副驾（自然语言投研）',
  ai03: '回测 Tear Sheet 解读员（杠杆/Alpha 判别 + 过拟合检测）',
  ai04: '盘前早报自动生成',
  ai05: '宏观风险雷达',
  ai06: '智能选股与归因',
  ai07: '策略自优化建议',
  ai08: '持仓诊断与风控',
}

const DEFAULT_ENABLED = true

interface AiPushState {
  /** 模块级 AI 推送偏好（后端权威 + 本地覆盖） */
  prefs: Record<string, { enabled: boolean; threshold: number | null }>
  loaded: boolean
  /** 从后端拉取最新偏好并合并到本地 */
  fetch: () => Promise<void>
  /** 更新单个模块偏好（本地即时 + 写回后端） */
  setPref: (
    module: AiModule,
    partial: Partial<{ enabled: boolean; threshold: number | null }>,
  ) => Promise<void>
  /** 批量保存（供设置面板整页保存） */
  save: (prefs: AiPushPref[]) => Promise<void>
  /** 运行时查询：是否允许该模块推送 */
  isEnabled: (module: string) => boolean
  /** 运行时查询：该模块的触发阈值（无配置回落 null） */
  thresholdOf: (module: string) => number | null
}

export const useAiPushPrefStore = create<AiPushState>()(
  persist(
    (set, get) => ({
      prefs: {},
      loaded: false,

      fetch: async () => {
        try {
          const res = await apiClient.get<{
            data: { prefs: AiPushPref[] }
            status: number
          }>('/settings/preferences/ai-push')
          const next: Record<string, { enabled: boolean; threshold: number | null }> = {}
          for (const p of res.data.prefs) {
            next[p.module] = { enabled: p.enabled, threshold: p.threshold }
          }
          set({ prefs: { ...get().prefs, ...next }, loaded: true })
        } catch {
          // 拉取失败不影响本地已有配置，仅标记已尝试加载
          set({ loaded: true })
        }
      },

      setPref: async (module, partial) => {
        const current = get().prefs[module] ?? { enabled: DEFAULT_ENABLED, threshold: null }
        const updated = { ...current, ...partial }
        set({ prefs: { ...get().prefs, [module]: updated } })
        // 增量写回后端；失败不阻塞本地（下次 fetch 会重新对齐）
        try {
          await apiClient.put('/settings/preferences/ai-push', {
            prefs: [{ module, ...updated }],
          })
        } catch {
          /* noop */
        }
      },

      save: async (prefs) => {
        await apiClient.put('/settings/preferences/ai-push', { prefs })
      },

      isEnabled: (module) => get().prefs[module]?.enabled ?? DEFAULT_ENABLED,
      thresholdOf: (module) => get().prefs[module]?.threshold ?? null,
    }),
    { name: STORAGE_KEYS.aiPush },
  ),
)
