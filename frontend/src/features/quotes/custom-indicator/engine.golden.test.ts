import { describe, it, expect, afterAll } from 'vitest'
import { readFileSync, writeFileSync } from 'fs'
import { join } from 'path'
import { evaluate } from './engine'

// 跨语言 golden fixtures：以本 TS 引擎为 ground truth 生成 expected，
// 后端 pytest (backend/tests/test_expr_evaluator.py) 加载同一份 JSON 断言 Python 端语义一致。
const p = join(__dirname, 'expr-golden.json')
const data = JSON.parse(readFileSync(p, 'utf-8'))
const UPDATE = process.env.UPDATE_GOLDEN === '1'

function approx(a: number | null, b: number | null, tol = 1e-6): boolean {
  if (a === null && b === null) return true
  if (a === null || b === null) return false
  return Math.abs(a - b) < tol
}

describe('expr-golden (TS ground truth)', () => {
  for (const c of data.cases) {
    it(c.name, () => {
      const r = evaluate(c.expr, data.bars, c.params || {})
      if (UPDATE) {
        // 注意：TS 返回字段为 isBool（驼峰），与 Python 端 is_bool 对齐后落盘
        c.expected = { ok: r.ok, is_bool: r.isBool, values: r.values }
      } else {
        const exp = c.expected
        expect(r.ok).toBe(exp.ok)
        if (r.ok) {
          expect(r.isBool).toBe(exp.is_bool)
          expect(r.values.length).toBe(exp.values.length)
          for (let i = 0; i < r.values.length; i++) {
            expect(approx(r.values[i], exp.values[i])).toBe(true)
          }
        }
      }
    })
  }
  afterAll(() => {
    if (UPDATE) writeFileSync(p, JSON.stringify(data, null, 2))
  })
})
