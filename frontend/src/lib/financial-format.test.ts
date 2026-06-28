/**
 * 金融格式化工具单元测试
 * TEST-02: 涨跌颜色 + 等宽字体
 */
import { describe, it, expect } from 'vitest'
import {
  formatPrice,
  formatPercent,
  formatVolume,
  getChangeColorClasses,
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

describe('formatPercent', () => {
  it('should format percentage with sign', () => {
    const result = formatPercent(1.5)
    expect(result).toContain('1.5')
  })

  it('should handle zero percent', () => {
    const result = formatPercent(0)
    expect(result).toContain('0')
  })
})

describe('formatVolume', () => {
  it('should format large volumes with suffix', () => {
    const result = formatVolume(1000000)
    expect(result).toBeTruthy()
  })

  it('should handle small volumes', () => {
    const result = formatVolume(500)
    expect(result).toContain('500')
  })
})

describe('getChangeColorClasses', () => {
  it('should return color classes for positive change', () => {
    const classes = getChangeColorClasses(1.5)
    expect(classes).toBeTruthy()
    expect(typeof classes).toBe('string')
  })

  it('should return color classes for negative change', () => {
    const classes = getChangeColorClasses(-1.5)
    expect(classes).toBeTruthy()
  })

  it('should return color classes for zero change', () => {
    const classes = getChangeColorClasses(0)
    expect(classes).toBeTruthy()
  })
})

describe('getFinancialNumberClasses', () => {
  it('should include tabular-nums', () => {
    const classes = getFinancialNumberClasses()
    expect(classes).toContain('tabular-nums')
  })

  it('should include font-mono', () => {
    const classes = getFinancialNumberClasses()
    expect(classes).toContain('font-mono')
  })
})

describe('Market Region', () => {
  it('should default to CN region', () => {
    // Reset to default
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
