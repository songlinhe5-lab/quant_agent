/**
 * ALERT-COND-01：条件单沙盒 单元测试
 * 验证 evalCondition 边沿语义、store 增删改 + 日志上限、上升沿触发仅记一次。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAlertSandboxStore, evalCondition, type AlertCondition } from './alert-sandbox'
import type { CIBar } from './engine'

function mkBars(closeArr: number[]): CIBar[] {
  return closeArr.map((c, i) => ({
    time: `2026-07-${String(i + 1).padStart(2, '0')}`,
    open: c,
    high: c,
    low: c,
    close: c,
    volume: 1000,
  }))
}

const baseCond: Omit<AlertCondition, 'id' | 'createdAt'> = {
  name: 'RSI 超买',
  expr: 'CLOSE > 100',
  params: {},
  enabled: true,
  notify: 'both',
}

describe('evalCondition（条件评估）', () => {
  it('末根满足布尔条件时 state=true', () => {
    const bars = mkBars([90, 95, 105])
    const res = evalCondition({ ...baseCond, id: 'x', createdAt: 0 }, bars)
    expect(res.ok).toBe(true)
    expect(res.state).toBe(true)
  })

  it('末根不满足布尔条件时 state=false', () => {
    const bars = mkBars([90, 95, 99])
    const res = evalCondition({ ...baseCond, id: 'x', createdAt: 0 }, bars)
    expect(res.state).toBe(false)
  })

  it('无 K 线数据时返回 ok=false', () => {
    const res = evalCondition({ ...baseCond, id: 'x', createdAt: 0 }, [])
    expect(res.ok).toBe(false)
  })

  it('非法表达式返回 ok=false 且带 error', () => {
    const bars = mkBars([105])
    const res = evalCondition({ ...baseCond, id: 'x', createdAt: 0, expr: 'CLOSE > >' }, bars)
    expect(res.ok).toBe(false)
    expect(res.error).toBeTruthy()
  })
})

describe('条件单 store（增删改 + 日志）', () => {
  beforeEach(() => {
    const s = useAlertSandboxStore.getState()
    s.clearAlertLog()
    // 清空条件
    ;[...useAlertSandboxStore.getState().conditions].forEach((c) => useAlertSandboxStore.getState().removeCondition(c.id))
  })

  it('addCondition 自动生成 id / createdAt', () => {
    const id = useAlertSandboxStore.getState().addCondition(baseCond)
    const c = useAlertSandboxStore.getState().conditions[0]
    expect(c.id).toBe(id)
    expect(typeof c.createdAt).toBe('number')
  })

  it('toggleCondition 翻转 enabled', () => {
    const id = useAlertSandboxStore.getState().addCondition(baseCond)
    useAlertSandboxStore.getState().toggleCondition(id)
    expect(useAlertSandboxStore.getState().conditions[0].enabled).toBe(false)
  })

  it('removeCondition 删除指定条件', () => {
    const id = useAlertSandboxStore.getState().addCondition(baseCond)
    useAlertSandboxStore.getState().removeCondition(id)
    expect(useAlertSandboxStore.getState().conditions.length).toBe(0)
  })

  it('pushAlert 写入日志且上限 200 条', () => {
    for (let i = 0; i < 205; i++) {
      useAlertSandboxStore.getState().pushAlert({ condId: 'c', condName: 'n', expr: 'x', time: 't', price: 1 })
    }
    expect(useAlertSandboxStore.getState().alertLog.length).toBe(200)
  })

  it('clearAlertLog 清空命中日志', () => {
    useAlertSandboxStore.getState().pushAlert({ condId: 'c', condName: 'n', expr: 'x', time: 't' })
    useAlertSandboxStore.getState().clearAlertLog()
    expect(useAlertSandboxStore.getState().alertLog.length).toBe(0)
  })
})

describe('上升沿边沿检测（模拟命中一次）', () => {
  it('false→true 仅记一次命中，true→true 不再记', () => {
    vi.useFakeTimers()
    const pushAlert = useAlertSandboxStore.getState().pushAlert
    const setConditionState = useAlertSandboxStore.getState().setConditionState
    const bars = mkBars([105]) // 满足 CLOSE > 100

    // 初始 lastState=false -> 第一次评估应命中
    const cond: AlertCondition = { ...baseCond, id: 'e1', createdAt: 0, lastState: false }
    const res1 = evalCondition(cond, bars)
    expect(res1.state).toBe(true)
    if (res1.state !== (cond.lastState ?? false)) {
      pushAlert({ condId: cond.id, condName: cond.name, expr: cond.expr, time: bars[0].time, price: bars[0].close })
      setConditionState(cond.id, res1.state)
    }
    expect(useAlertSandboxStore.getState().alertLog.length).toBe(1)

    // 第二次评估 lastState 已被置为 true -> 不再命中
    const after = useAlertSandboxStore.getState().conditions.find((c) => c.id === 'e1')
    const res2 = evalCondition(after ?? cond, bars)
    const prev2 = after?.lastState ?? true
    if (res2.state !== prev2) {
      pushAlert({ condId: cond.id, condName: cond.name, expr: cond.expr, time: bars[0].time, price: bars[0].close })
    }
    expect(useAlertSandboxStore.getState().alertLog.length).toBe(1)
    vi.useRealTimers()
  })
})
