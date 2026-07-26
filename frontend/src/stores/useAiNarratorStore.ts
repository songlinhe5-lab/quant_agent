'use client'

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import { AI_NARRATOR_DEFAULT_THRESHOLD, STORAGE_KEYS, type AiNarratorThreshold } from '@/lib/constants'

interface AiNarratorState {
  /** 是否开启异动解说（K 线浮动气泡） */
  enabled: boolean
  /** 异动触发阈值（涨跌幅 %） */
  threshold: AiNarratorThreshold
  /** 是否开启盘口大单集中检测（盘口面板底部一行提示） */
  orderBookAiEnabled: boolean
  setEnabled: (v: boolean) => void
  setThreshold: (v: AiNarratorThreshold) => void
  setOrderBookAiEnabled: (v: boolean) => void
}

/**
 * AI-01 异动解说员开关与阈值。
 * 设计原则：可关闭（enabled / orderBookAiEnabled）、有阈值（threshold）、可折叠（前端气泡默认一行摘要）。
 */
export const useAiNarratorStore = create<AiNarratorState>()(
  persist(
    (set) => ({
      enabled: true,
      threshold: AI_NARRATOR_DEFAULT_THRESHOLD,
      orderBookAiEnabled: true,
      setEnabled: (v) => set({ enabled: v }),
      setThreshold: (v) => set({ threshold: v }),
      setOrderBookAiEnabled: (v) => set({ orderBookAiEnabled: v }),
    }),
    { name: STORAGE_KEYS.aiNarrator },
  ),
)
