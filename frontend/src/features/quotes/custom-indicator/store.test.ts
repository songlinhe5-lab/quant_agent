/**
 * store.test.ts — 策略配方持久化（PROD-11 COND-01）
 * 验证 saveRecipe / removeRecipe 的 in-memory 行为 + 字段完整性。
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { useCustomIndicatorStore, type StrategyRecipe } from './store'

describe('策略配方持久化（COND-01）', () => {
  beforeEach(() => {
    // 每个用例前清空配方，避免用例间串扰
    useCustomIndicatorStore.setState({ recipes: [] })
  })

  const sample: Omit<StrategyRecipe, 'id' | 'createdAt'> = {
    name: 'RSI 最优',
    description: '备注',
    indicatorName: 'RSI 共振',
    expr: 'RSI(@n) > 50',
    params: { n: 14 },
    sortBy: 'totalReturnPct',
    metrics: { totalReturnPct: 12.3, sharpe: 1.2, winRatePct: 60, maxDrawdownPct: 5, trades: 10 },
  }

  it('saveRecipe 追加一条配方并自动生成 id / createdAt', () => {
    useCustomIndicatorStore.getState().saveRecipe(sample)
    const recipes = useCustomIndicatorStore.getState().recipes
    expect(recipes.length).toBe(1)
    const r = recipes[0]
    expect(r.id).toBeTruthy()
    expect(r.createdAt).toBeGreaterThan(0)
    expect(r.params).toEqual({ n: 14 })
    expect(r.metrics?.totalReturnPct).toBe(12.3)
    expect(r.description).toBe('备注')
  })

  it('saveRecipe 不传 description 时该字段为 undefined', () => {
    const { description: _omit, ...noDesc } = sample
    useCustomIndicatorStore.getState().saveRecipe(noDesc)
    const r = useCustomIndicatorStore.getState().recipes[0]
    expect(r.description).toBeUndefined()
  })

  it('removeRecipe 删除指定配方', () => {
    useCustomIndicatorStore.getState().saveRecipe(sample)
    const id = useCustomIndicatorStore.getState().recipes[0].id
    useCustomIndicatorStore.getState().removeRecipe(id)
    expect(useCustomIndicatorStore.getState().recipes.length).toBe(0)
  })

  it('多配方按保存顺序追加', () => {
    useCustomIndicatorStore.getState().saveRecipe({ ...sample, name: 'A', params: { n: 1 }, sortBy: 'totalReturnPct' })
    useCustomIndicatorStore.getState().saveRecipe({ ...sample, name: 'B', params: { n: 2 }, sortBy: 'sharpe' })
    const recipes = useCustomIndicatorStore.getState().recipes
    expect(recipes.length).toBe(2)
    expect(recipes[0].name).toBe('A')
    expect(recipes[1].name).toBe('B')
    expect(recipes[1].sortBy).toBe('sharpe')
  })
})
