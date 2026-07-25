/**
 * PROD-11：自定义指标脚本编辑面板（图表内抽屉）。
 * 列出用户指标、支持新增/编辑/删除/显隐，并实时做语法校验与结果预览。
 */
import { useState, useEffect } from 'react'
import { Plus, Pencil, Trash2, Eye, EyeOff, X, HelpCircle, Sigma } from 'lucide-react'
import { useCustomIndicatorStore, type CustomIndicator } from './store'
import { validate, evaluate, type CIBar } from './engine'

const PRESET_COLORS = ['#a855f7', '#10b981', '#ef4444', '#3b82f6', '#f59e0b', '#ec4899', '#14b8a6']

const SYNTAX_HELP = [
  ['字段', 'OPEN HIGH LOW CLOSE VOLUME'],
  ['命名空间', 'KDJ.K / KDJ.D / KDJ.J · MACD.DIFF / MACD.DEA / MACD.HIST · BB.UPPER / BB.LOWER / BB.MID'],
  ['函数', 'MA(x,n) EMA(x,n) RSI(x,n) REF(x,n) CROSS(a,b) HHV(x,n) LLV(x,n) ABS(x) SQRT(x) MAX(a,b) MIN(a,b)'],
  ['运算符', '+ - * / % · > < >= <= == != · && || ! （也可用 AND/OR/NOT）'],
  ['示例', 'RSI(14) > KDJ.K ｜ CROSS(MA(CLOSE,5), MA(CLOSE,20)) ｜ (CLOSE-MA(CLOSE,20))/MA(CLOSE,20)*100'],
]

export function CustomIndicatorPanel({
  open,
  onClose,
  bars,
}: {
  open: boolean
  onClose: () => void
  bars: CIBar[]
}) {
  const { indicators, signalLog, add, update, remove, toggle, clearSignals } = useCustomIndicatorStore()
  const [editing, setEditing] = useState<CustomIndicator | null>(null)
  const [name, setName] = useState('')
  const [expr, setExpr] = useState('')
  const [color, setColor] = useState('#a855f7')
  const [pane, setPane] = useState<'overlay' | 'separate' | 'auto'>('auto')
  const [showHelp, setShowHelp] = useState(false)

  useEffect(() => {
    if (editing) {
      setName(editing.name)
      setExpr(editing.expr)
      setColor(editing.color)
      setPane(editing.pane ?? 'auto')
    }
  }, [editing])

  if (!open) return null

  const startNew = () => setEditing({ id: '', name: '', expr: '', color: '#a855f7', visible: true })
  const cancel = () => setEditing(null)
  const save = () => {
    if (!name.trim() || !expr.trim()) return
    if (!validate(expr).ok) return
    const finalPane = pane === 'auto' ? undefined : pane
    if (editing && editing.id) update(editing.id, { name: name.trim(), expr: expr.trim(), color, pane: finalPane })
    else add({ name: name.trim(), expr: expr.trim(), color, visible: true, pane: finalPane })
    setEditing(null)
  }

  const v = expr.trim() ? validate(expr.trim()) : { ok: true }
  const preview =
    editing && expr.trim() && v.ok && bars.length
      ? evaluate(expr.trim(), bars)
      : null

  let previewText = ''
  if (preview && preview.ok) {
    if (preview.isBool) {
      const last = [...preview.values].reverse().find((x) => x != null)
      previewText = `类型: 布尔信号 ｜ 最新状态: ${last === 1 ? '成立 ✅' : last === 0 ? '不成立' : '—'}`
    } else {
      const last = [...preview.values].reverse().find((x) => x != null)
      previewText = `类型: 数值序列 ｜ 最新值: ${last != null ? Number(last).toFixed(3) : '—'}`
    }
  }

  return (
    <div className="absolute right-2 top-9 z-30 w-[340px] max-h-[calc(100%-3.5rem)] flex flex-col rounded-lg border border-border/60 bg-background/95 backdrop-blur shadow-2xl overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/40">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
          <Sigma className="h-3.5 w-3.5 text-primary" /> 自定义指标
          <span className="text-[10px] font-normal text-muted-foreground">Pine Script 简化版</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setShowHelp((s) => !s)} title="语法帮助" className="p-1 rounded hover:bg-muted/60 text-muted-foreground">
            <HelpCircle className="h-3.5 w-3.5" />
          </button>
          <button onClick={onClose} title="关闭" className="p-1 rounded hover:bg-muted/60 text-muted-foreground">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {showHelp && (
          <div className="space-y-1.5 rounded-md border border-border/40 bg-muted/30 p-2 text-[10px] leading-relaxed text-muted-foreground">
            {SYNTAX_HELP.map(([k, val]) => (
              <div key={k}>
                <span className="text-foreground font-medium">{k}：</span>
                <span className="font-mono break-all">{val}</span>
              </div>
            ))}
          </div>
        )}

        {!editing &&
          indicators.map((ind) => (
            <div key={ind.id} className="flex items-center gap-2 rounded-md border border-border/40 bg-background px-2 py-1.5">
              <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: ind.color }} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[11px] font-medium text-foreground">{ind.name}</div>
                <div className="truncate font-mono text-[9px] text-muted-foreground">{ind.expr}</div>
                <div className="text-[9px] text-slate-500">叠加: {ind.pane === 'separate' ? '独立副图' : ind.pane === 'overlay' ? '主图' : '自动'}</div>
              </div>
              <button onClick={() => toggle(ind.id)} title={ind.visible ? '隐藏' : '显示'} className="p-1 rounded hover:bg-muted/60 text-muted-foreground">
                {ind.visible ? <Eye className="h-3 w-3 text-emerald-400" /> : <EyeOff className="h-3 w-3" />}
              </button>
              <button onClick={() => setEditing(ind)} title="编辑" className="p-1 rounded hover:bg-muted/60 text-muted-foreground">
                <Pencil className="h-3 w-3" />
              </button>
              <button onClick={() => remove(ind.id)} title="删除" className="p-1 rounded hover:bg-muted/60 text-red-400">
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          )        )}

        {!editing && signalLog.length > 0 && (
          <div className="space-y-1 rounded-md border border-border/40 bg-muted/20 p-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-medium text-foreground">信号触发日志</span>
              <button onClick={clearSignals} className="text-[9px] text-muted-foreground hover:text-red-400">清空</button>
            </div>
            {signalLog.slice(0, 12).map((s, i) => (
              <div key={i} className="flex items-center gap-1.5 text-[9px]">
                <span className="text-slate-500 font-mono shrink-0">{s.time}</span>
                <span className="truncate flex-1 text-foreground">{s.indName}</span>
                <span className="font-mono text-muted-foreground truncate max-w-[120px]">{s.expr}</span>
              </div>
            ))}
          </div>
        )}

        {!editing && (
          <button
            onClick={startNew}
            className="flex w-full items-center justify-center gap-1 rounded-md border border-dashed border-border/60 py-1.5 text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" /> 新增自定义指标
          </button>
        )}

        {editing && (
          <div className="space-y-2 rounded-md border border-border/50 bg-muted/20 p-2.5">
            <div>
              <label className="mb-1 block text-[10px] text-muted-foreground">名称</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="如：RSI 与 KDJ 共振"
                className="w-full rounded border border-border/50 bg-background px-2 py-1 text-[11px] text-foreground outline-none focus:border-primary"
              />
            </div>
            <div>
              <label className="mb-1 block text-[10px] text-muted-foreground">表达式</label>
              <textarea
                value={expr}
                onChange={(e) => setExpr(e.target.value)}
                rows={3}
                placeholder="如：RSI(14) > KDJ.K"
                className="w-full resize-none rounded border border-border/50 bg-background px-2 py-1 font-mono text-[11px] text-foreground outline-none focus:border-primary"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground">颜色</span>
              {PRESET_COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => setColor(c)}
                  className={`h-4 w-4 rounded-full border ${color === c ? 'border-foreground' : 'border-transparent'}`}
                  style={{ backgroundColor: c }}
                />
              ))}
              <input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="ml-auto h-5 w-6 cursor-pointer rounded border border-border/50 bg-transparent" />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground">叠加</span>
              {(['auto', 'overlay', 'separate'] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setPane(p)}
                  className={`rounded px-1.5 py-0.5 text-[10px] border ${pane === p ? 'border-primary text-primary bg-primary/10' : 'border-border/50 text-muted-foreground'}`}
                >
                  {p === 'auto' ? '自动' : p === 'overlay' ? '主图' : '副图'}
                </button>
              ))}
            </div>

            {expr.trim() && !v.ok && (
              <div className="rounded bg-red-500/10 px-2 py-1 text-[10px] text-red-400">语法错误：{v.error}</div>
            )}
            {previewText && (
              <div className="rounded bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-400 font-mono">{previewText}</div>
            )}

            <div className="flex items-center justify-end gap-2 pt-1">
              <button onClick={cancel} className="rounded px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-muted/60">取消</button>
              <button
                onClick={save}
                disabled={!name.trim() || !expr.trim() || !v.ok}
                className="rounded bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-foreground disabled:opacity-40"
              >
                {editing.id ? '保存' : '添加'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
