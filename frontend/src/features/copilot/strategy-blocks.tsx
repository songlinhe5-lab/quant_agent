/**
 * COPILOT-11: 策略部署卡片
 * 渲染后端标记的 strategyBlocks，附带一键部署按钮跳转策略工作台。
 */
import { Rocket } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { StrategyBlock } from './types'

export function StrategyBlocks({ blocks }: { blocks: StrategyBlock[] }) {
  const navigate = useNavigate()

  return (
    <div className="mt-4 space-y-3">
      {blocks.map((block, bIdx) => (
        <div key={bIdx} className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 dark:bg-emerald-500/10 overflow-hidden shadow-sm">
          <div className="flex items-center justify-between px-4 py-2.5 bg-emerald-500/10 border-b border-emerald-500/20">
            <div className="flex items-center gap-2">
              <Rocket className="h-4 w-4 text-emerald-500" />
              <span className="text-xs font-bold text-emerald-600 dark:text-emerald-400">策略代码 (Strategy Block)</span>
              <span className="text-[10px] text-muted-foreground font-mono">{block.code.split('\n').length} 行</span>
            </div>
            <button
              onClick={() => {
                sessionStorage.setItem('quant_strategy_initial_code', block.code)
                window.dispatchEvent(new CustomEvent('quant_strategy_code_invoke', { detail: { code: block.code } }))
                const tabTrigger = document.querySelector('[role="tab"][value="strategy"], [data-value="strategy"], a[href="/strategy"], a[href="#strategy"]') as HTMLElement
                if (tabTrigger) tabTrigger.click()
                else navigate('/strategy')
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-bold shadow-sm hover:shadow-md transition-all"
            >
              <Rocket className="h-3 w-3" />
              一键部署
            </button>
          </div>
          <div className="overflow-x-auto custom-scrollbar text-[11px] leading-relaxed max-h-64">
            <pre className="p-3 font-mono text-slate-700 dark:text-slate-300 whitespace-pre">{block.code}</pre>
          </div>
        </div>
      ))}
    </div>
  )
}
