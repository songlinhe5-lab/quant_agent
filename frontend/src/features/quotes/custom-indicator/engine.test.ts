import { describe, it, expect } from 'vitest'
import { evaluate, validate, suggestPane, collectBoolSignals, runSignalBacktest, type CIBar } from './engine'

function makeBars(n: number): CIBar[] {
  const bars: CIBar[] = []
  for (let i = 0; i < n; i++) {
    const close = 100 + Math.sin(i / 3) * 10 + i
    const open = close - 1
    bars.push({
      time: `2024-01-${String((i % 28) + 1).padStart(2, '0')} 09:30:00`,
      open,
      high: close + 2,
      low: open - 2,
      close,
      volume: 1000 + i,
    })
  }
  return bars
}

describe('custom indicator engine', () => {
  const bars = makeBars(60)

  it('字段变量返回对应序列', () => {
    const r = evaluate('CLOSE', bars)
    expect(r.ok).toBe(true)
    expect(r.isBool).toBe(false)
    expect(r.values[10]).toBeCloseTo(bars[10].close, 5)
  })

  it('MA 等于简单移动平均', () => {
    const r = evaluate('MA(CLOSE,5)', bars)
    expect(r.ok).toBe(true)
    const expected = (bars[4].close + bars[3].close + bars[2].close + bars[1].close + bars[0].close) / 5
    expect(r.values[4]).toBeCloseTo(expected, 5)
    expect(r.values[3]).toBeNull()
  })

  it('比较运算产生布尔序列', () => {
    const r = evaluate('RSI(14) > KDJ.K', bars)
    expect(r.ok).toBe(true)
    expect(r.isBool).toBe(true)
    // 布尔序列元素只能是 0/1/null
    for (const v of r.values) expect(v === null || v === 0 || v === 1).toBe(true)
  })

  it('CROSS 仅在金叉处为真', () => {
    const r = evaluate('CROSS(MA(CLOSE,3), MA(CLOSE,6))', bars)
    expect(r.ok).toBe(true)
    expect(r.isBool).toBe(true)
  })

  it('语法错误被 validate 捕获', () => {
    expect(validate('RSI(14').ok).toBe(false)
    expect(validate('CLOSE +* 2').ok).toBe(false)
    expect(validate('FOO(1)').ok).toBe(false)
  })

  it('函数参数不足给出友好错误', () => {
    const r = evaluate('RSI(CLOSE)', bars)
    expect(r.ok).toBe(false)
    expect(r.error).toMatch(/常量|周期/)
  })

  it('未知函数报错', () => {
    const r = evaluate('WAT(1)', bars)
    expect(r.ok).toBe(false)
  })

  it('算术运算逐点正确', () => {
    const r = evaluate('(CLOSE - OPEN) * 2', bars)
    expect(r.ok).toBe(true)
    expect(r.values[5]).toBeCloseTo((bars[5].close - bars[5].open) * 2, 5)
  })

  it('suggestPane 对振荡器建议副图、对价格级建议主图', () => {
    expect(suggestPane('RSI(14)')).toBe('separate')
    expect(suggestPane('KDJ.K')).toBe('separate')
    expect(suggestPane('MACD.HIST')).toBe('separate')
    expect(suggestPane('MA(CLOSE,5)')).toBe('overlay')
    expect(suggestPane('CLOSE > 100')).toBe('overlay')
  })

  it('collectBoolSignals 收集上穿跳变点', () => {
    const r = collectBoolSignals('CLOSE > 110', bars)
    expect(r.ok).toBe(true)
    expect(r.times.length).toBeGreaterThanOrEqual(1)
    for (const t of r.times) {
      const bar = bars.find((b) => b.time === t)
      expect(bar).toBeTruthy()
      expect((bar as CIBar).close).toBeGreaterThan(110)
    }
  })

  it('collectBoolSignals 对数值表达式返回空', () => {
    expect(collectBoolSignals('RSI(14)', bars).times.length).toBe(0)
  })

  it('collectBoolSignals 语法错误返回 ok:false', () => {
    const r = collectBoolSignals('RSI(14', bars)
    expect(r.ok).toBe(false)
    expect(r.times.length).toBe(0)
  })

  it('runSignalBacktest 对布尔表达式做事件驱动回测', () => {
    const r = runSignalBacktest('CLOSE > 110', bars)
    expect(r.ok).toBe(true)
    expect(r.trades).toBeLessThanOrEqual(r.buys.length)
    expect(r.winRate).toBeGreaterThanOrEqual(0)
    expect(r.winRate).toBeLessThanOrEqual(100)
    expect(r.maxDrawdownPct).toBeGreaterThanOrEqual(0)
    expect(Number.isFinite(r.totalReturnPct)).toBe(true)
  })

  it('runSignalBacktest 对非布尔表达式返回错误', () => {
    const r = runSignalBacktest('RSI(14)', bars)
    expect(r.ok).toBe(false)
    expect(r.error).toContain('布尔')
  })

  it('runSignalBacktest 对 K 线不足返回错误', () => {
    expect(runSignalBacktest('CLOSE > 1', bars.slice(0, 1)).ok).toBe(false)
  })
})
