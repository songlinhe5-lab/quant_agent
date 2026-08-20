import { useState, useCallback } from 'react'
import { Rocket, ShieldCheck, AlertTriangle, X, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useStrategySandbox } from './use-strategy-sandbox'

/**
 * STRAT-07 / Frame 3: 部署至 OMS 确认闸门。
 * SANDBOX -> 仅纸面/模拟账本, 不发真实订单;
 * LIVE -> 需通过 REAL_TRADE_EXECUTE 校验(后端), 弹窗转红 + 二次确认。
 * 取代原无闸门直连按钮。
 */
interface GateState {
  className: string
  params: Record<string, any>
}

export function useDeployGate() {
  const { handleDeployToOMS } = useStrategySandbox()
  const [gate, setGate] = useState<GateState | null>(null)
  const [env, setEnv] = useState<'sandbox' | 'live'>('sandbox')
  const [liveConfirm, setLiveConfirm] = useState(false)
  const [isDeploying, setIsDeploying] = useState(false)

  const openDeployGate = useCallback((state: GateState) => {
    setGate(state)
    setEnv('sandbox')
    setLiveConfirm(false)
  }, [])

  const closeGate = useCallback(() => {
    if (isDeploying) return
    setGate(null)
  }, [isDeploying])

  const confirmDeploy = useCallback(async () => {
    if (!gate) return
    // LIVE 必须先二次确认
    if (env === 'live' && !liveConfirm) {
      setLiveConfirm(true)
      return
    }
    setIsDeploying(true)
    try {
      await handleDeployToOMS(gate.className, gate.params, env)
    } finally {
      setIsDeploying(false)
      setGate(null)
    }
  }, [gate, env, liveConfirm, handleDeployToOMS])

  const gateDialog = gate ? (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={closeGate}>
      <div
        className="w-full max-w-md rounded-xl border border-border/40 bg-[#1C1F28] shadow-2xl animate-in fade-in zoom-in-95"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/40">
          <Rocket className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold text-foreground">部署至 OMS · 确认闸门</span>
          <span className="ml-auto text-[10px] text-muted-foreground font-mono">{gate.className}.py</span>
          <button onClick={closeGate} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="p-4 space-y-2">
          {/* 环境选择 */}
          <button
            onClick={() => { setEnv('sandbox'); setLiveConfirm(false) }}
            className={`w-full flex items-center gap-3 p-3 rounded-lg border text-left text-xs transition-colors ${env === 'sandbox' ? 'border-amber-500/60 bg-amber-500/10' : 'border-border/50 bg-transparent hover:bg-secondary/40'}`}
          >
            <span className={`h-3.5 w-3.5 rounded-full border-2 flex items-center justify-center shrink-0 ${env === 'sandbox' ? 'border-amber-500' : 'border-muted-foreground'}`}>
              {env === 'sandbox' && <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />}
            </span>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="font-semibold flex items-center gap-1"><ShieldCheck className="h-3 w-3 text-amber-500" /> SANDBOX</span>
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-500 font-semibold">当前环境</span>
              </div>
              <p className="text-[10px] text-muted-foreground mt-0.5">仅纸面 / 模拟账本，不发真实订单</p>
            </div>
          </button>

          <button
            onClick={() => setEnv('live')}
            className={`w-full flex items-center gap-3 p-3 rounded-lg border text-left text-xs transition-colors ${env === 'live' ? 'border-red-500/60 bg-red-500/10' : 'border-border/50 bg-transparent hover:bg-secondary/40'}`}
          >
            <span className={`h-3.5 w-3.5 rounded-full border-2 flex items-center justify-center shrink-0 ${env === 'live' ? 'border-red-500' : 'border-muted-foreground'}`}>
              {env === 'live' && <span className="h-1.5 w-1.5 rounded-full bg-red-500" />}
            </span>
            <div className="flex-1">
              <div className="font-semibold text-red-500">LIVE</div>
              <p className="text-[10px] text-muted-foreground mt-0.5">须先通过 REAL_TRADE_EXECUTE 校验</p>
            </div>
          </button>

          {/* LIVE 二次确认 */}
          {env === 'live' && (
            <div className="mt-1 p-3 rounded-lg border border-red-500/40 bg-red-500/5">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-3.5 w-3.5 text-red-500 shrink-0" />
                <span className="text-[11px] font-semibold text-red-500">LIVE · 二次确认</span>
              </div>
              <p className="text-[10px] text-red-500/80 mt-1 leading-relaxed">
                将向 OMS 发送真实订单，确认环境变量 REAL_TRADE_EXECUTE=true？（后端将校验，未开启则拒绝）
              </p>
              {liveConfirm && (
                <div className="mt-2 flex items-center gap-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-red-500" />
                  <span className="text-[10px] text-red-500">请再次点击"确认部署 (LIVE)"以最终确认</span>
                </div>
              )}
            </div>
          )}

          <div className="flex items-center gap-2 pt-2">
            {env === 'live' ? (
              <Button
                onClick={confirmDeploy}
                disabled={isDeploying}
                className="flex-1 h-9 text-xs gap-1.5 bg-red-600 hover:bg-red-700 text-white"
              >
                {isDeploying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                {isDeploying ? '部署中...' : liveConfirm ? '确认部署 (LIVE)' : '下一步'}
              </Button>
            ) : (
              <Button
                onClick={confirmDeploy}
                disabled={isDeploying}
                className="flex-1 h-9 text-xs gap-1.5 bg-blue-600 hover:bg-blue-700 text-white"
              >
                {isDeploying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Rocket className="h-3.5 w-3.5" />}
                {isDeploying ? '部署中...' : '确认部署 (SANDBOX)'}
              </Button>
            )}
            <Button variant="outline" onClick={closeGate} disabled={isDeploying} className="h-9 text-xs text-muted-foreground">
              返回
            </Button>
          </div>
        </div>
      </div>
    </div>
  ) : null

  return { openDeployGate, gateDialog, isDeploying }
}
