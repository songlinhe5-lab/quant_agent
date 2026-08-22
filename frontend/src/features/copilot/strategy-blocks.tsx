/**
 * COPILOT-11: 策略部署卡片
 * COPILOT-22: SANDBOX 徽章 + 深链 /strategy?code= 携带代码块
 */
import { Rocket, ShieldOff } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useTradingModeStore } from '@/stores/useTradingModeStore'
import type { StrategyBlock } from './types'

export function StrategyBlocks({ blocks }: { blocks: StrategyBlock[] }) {
  const navigate = useNavigate()
  const mode = useTradingModeStore((s) => s.mode)
  // COPILOT-22: LIVE 文案只在 REAL_TRADE_EXECUTE 闸门通过(即交易模式确为 LIVE)后出现
  const isLive = mode === 'LIVE'

  return (
    <div className="mt-4 space-y-3">
      {blocks.map((block, bIdx) => {
        // 深链携带代码块：后端 strategy_code 无 id，用 base64 编码的 code 作深链（配合 sessionStorage 主路径）
        const codeParam = btoa(encodeURIComponent(block.code))
        return (
          <div key={bIdx} className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 dark:bg-emerald-500/10 overflow-hidden shadow-sm">
            <div className="flex items-center justify-between px-4 py-2.5 bg-emerald-500/10 border-b border-emerald-500/20">
              <div className="flex items-center gap-2">
                <Rocket className="h-4 w-4 text-emerald-500" />
                <span className="text-xs font-bold text-emerald-600 dark:text-emerald-400">策略代码</span>
                <span className="text-[10px] text-muted-foreground font-mono">{block.code.split('\n').length} 行</span>
                {/* COPILOT-22: SANDBOX 徽章 —— LIVE 文案不出现在闸门通过之前 */}
                <span className={cn('flex items-center gap-1 rounded border px-1.5 py-px text-[8px] font-bold', isLive ? 'border-red-500/40 bg-red-500/10 text-red-400' : 'border-amber-500/40 bg-amber-500/10 text-amber-400')}>
                  <ShieldOff className="h-2.5 w-2.5" />
                  {isLive ? 'LIVE · 已实盘' : 'SANDBOX · 未实盘'}
                </span>
              </div>
              <button
                onClick={() => {
                  sessionStorage.setItem('quant_strategy_initial_code', block.code)
                  window.dispatchEvent(new CustomEvent('quant_strategy_code_invoke', { detail: { code: block.code } }))
                  navigate(`/strategy?code=${codeParam}`)
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-bold shadow-sm hover:shadow-md transition-all"
              >
                <Rocket className="h-3 w-3" />
                去策略研发工作台
              </button>
            </div>
            <div className="overflow-x-auto custom-scrollbar text-[11px] leading-relaxed max-h-64">
              <pre className="p-3 font-mono text-slate-700 dark:text-slate-300 whitespace-pre">{block.code}</pre>
            </div>
          </div>
        )
      })}
    </div>
  )
}
