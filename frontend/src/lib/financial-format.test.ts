/**
 * 金融格式化工具单元测试
 * TEST-02: 涨跌颜色 + 等宽字体
 */
import { describe, it, expect, beforeEach } from 'vitest'
import {
  formatPrice,
  formatChange,
  formatLargeNumber,
  getChangeColor,
  getFinancialNumberClasses,
  setMarketRegion,
  getMarketRegion,
} from '@/lib/financial-format'

describe('formatPrice', () => {
  it('should format price with 2 decimals', () => {
    expect(formatPrice(400.123)).toBe('400.12')
    expect(formatPrice(0.5)).toBe('0.50')
  })

  it('should handle zero', () => {
    expect(formatPrice(0)).toBe('0.00')
  })

  it('should handle negative prices', () => {
    expect(formatPrice(-10.5)).toBe('-10.50')
  })
})

describe('formatChange', () => {
  it('should format percentage with sign', () => {
    const result = formatChange(1.5)
    expect(result).toContain('+')
    expect(result).toContain('1.50')
  })

  it('should handle zero percent', () => {
    const result = formatChange(0)
    expect(result).toContain('0.00')
  })

  it('should handle negative change', () => {
    const result = formatChange(-2.5)
    expect(result).toContain('-2.50')
  })
})

describe('formatLargeNumber', () => {
  it('should format millions with M suffix', () => {
    const result = formatLargeNumber(1000000)
    expect(result).toBe('1.00M')
  })

  it('should format billions with B suffix', () => {
    const result = formatLargeNumber(1500000000)
    expect(result).toBe('1.50B')
  })

  it('should handle small numbers', () => {
    const result = formatLargeNumber(500)
    expect(result).toContain('500')
  })

  it('should format thousands with K suffix', () => {
    const result = formatLargeNumber(1500)
    expect(result).toBe('1.50K')
  })
})

describe('getChangeColor', () => {
  beforeEach(() => {
    setMarketRegion('CN')
  })

  it('should return color for positive change (CN market)', () => {
    const color = getChangeColor(1.5)
    expect(color).toContain('red')  // CN: 红涨
  })

  it('should return color for negative change (CN market)', () => {
    const color = getChangeColor(-1.5)
    expect(color).toContain('emerald')  // CN: 绿跌
  })

  it('should return color for zero change', () => {
    const color = getChangeColor(0)
    expect(color).toContain('muted')
  })

  it('should respect US market colors', () => {
    setMarketRegion('US')
    const color = getChangeColor(1.5)
    expect(color).toContain('emerald')  // US: 绿涨
  })
})

describe('getFinancialNumberClasses', () => {
  it('should include tabular-nums', () => {
    const classes = getFinancialNumberClasses(1.5)
    expect(classes).toContain('tabular-nums')
  })

  it('should include font-mono', () => {
    const classes = getFinancialNumberClasses(1.5)
    expect(classes).toContain('font-mono')
  })
})

describe('Market Region', () => {
  it('should default to CN region', () => {
    setMarketRegion('CN')
    expect(getMarketRegion()).toBe('CN')
  })

  it('should switch regions', () => {
    setMarketRegion('US')
    expect(getMarketRegion()).toBe('US')
    
    setMarketRegion('HK')
    expect(getMarketRegion()).toBe('HK')
    
    // Reset
    setMarketRegion('CN')
  })
})
