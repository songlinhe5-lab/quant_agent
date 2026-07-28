/**
 * PROD-11: 自定义指标表达式引擎（对标 TradingView Pine Script 简化版）
 *
 * 设计原则：
 * - 纯函数、零外部依赖、可在主线程同步计算（数据量受图表 K 线数限制，不会 OOM）。
 * - 所有序列与 K 线严格对齐（索引 i 对应第 i 根 K 线），输出长度 = bars.length。
 * - 单根 K 线数据不足（指标预热期）用 null 表示，运算中任一侧为 null 则结果 null。
 *
 * 语法（对标 Pine，简化）：
 *   字段:    OPEN HIGH LOW CLOSE VOLUME VOL TIME
 *   命名空间: KDJ.K / KDJ.D / KDJ.J | MACD.DIFF / MACD.DEA / MACD.HIST | BB.UPPER / BB.LOWER / BB.MID
 *   函数:    MA(x,n) EMA(x,n) RSI(x,n) REF(x,n) CROSS(a,b) HHV(x,n) LLV(x,n)
 *           ABS(x) SQRT(x) MAX(a,b) MIN(a,b)
 *   运算符:  + - * / %  |  > < >= <= == !=  |  && || !  (也支持 AND/OR/NOT 关键字)
 *   字面量:  数字（如 14, 1.5, -2）
 *   参数:    @name（用户自定义参数，如 @period，保存于指标上，运行时代入）
 *
 * 求值结果:
 *   - 数值序列（如 RSI(14)、MA(CLOSE,20)）→ 主图叠加 LineSeries
 *   - 布尔序列（如 RSI(14) > KDJ.K、CROSS(MA(CLOSE,5), MA(CLOSE,20))）→ 主图信号点
 */

export interface CIBar {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface EvalResult {
  ok: boolean
  isBool: boolean
  values: (number | null)[]
  error?: string
}

// ─── Tokenizer ────────────────────────────────────────────────────────
type Tok =
  | { t: 'num'; v: number }
  | { t: 'id'; v: string }
  | { t: 'param'; v: string }
  | { t: 'op'; v: string }
  | { t: 'dot' }
  | { t: 'lp' }
  | { t: 'rp' }
  | { t: 'comma' }

const isDigit = (c: string) => c >= '0' && c <= '9'
const isAlpha = (c: string) => (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c === '_'

function tokenize(src: string): Tok[] {
  const toks: Tok[] = []
  let i = 0
  while (i < src.length) {
    const c = src[i]
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r') { i++; continue }
    if (isDigit(c) || (c === '.' && isDigit(src[i + 1] ?? ''))) {
      let j = i + 1
      while (j < src.length && (isDigit(src[j]) || src[j] === '.')) j++
      toks.push({ t: 'num', v: parseFloat(src.slice(i, j)) }); i = j; continue
    }
    if (isAlpha(c)) {
      let j = i + 1
      while (j < src.length && (isAlpha(src[j]) || isDigit(src[j]))) j++
      const word = src.slice(i, j)
      const up = word.toUpperCase()
      if (up === 'AND' || up === 'OR' || up === 'NOT') toks.push({ t: 'op', v: up === 'AND' ? '&&' : up === 'OR' ? '||' : '!' })
      else toks.push({ t: 'id', v: up })
      i = j; continue
    }
    if (c === '@') {
      let j = i + 1
      if (j < src.length && (isAlpha(src[j]) || isDigit(src[j]))) {
        while (j < src.length && (isAlpha(src[j]) || isDigit(src[j]))) j++
        toks.push({ t: 'param', v: src.slice(i + 1, j) }); i = j; continue
      }
      throw new Error(`无法识别的字符 "@"（参数须以字母/数字命名，如 @period）`)
    }
    const two = src.slice(i, i + 2)
    if (two === '>=' || two === '<=' || two === '==' || two === '!=' || two === '&&' || two === '||') {
      toks.push({ t: 'op', v: two }); i += 2; continue
    }
    if (c === '>' || c === '<' || c === '+' || c === '-' || c === '*' || c === '/' || c === '%' || c === '!') {
      toks.push({ t: 'op', v: c }); i++; continue
    }
    if (c === '.') { toks.push({ t: 'dot' }); i++; continue }
    if (c === '(') { toks.push({ t: 'lp' }); i++; continue }
    if (c === ')') { toks.push({ t: 'rp' }); i++; continue }
    if (c === ',') { toks.push({ t: 'comma' }); i++; continue }
    throw new Error(`无法识别的字符 "${c}"（位置 ${i}）`)
  }
  return toks
}

// ─── AST ──────────────────────────────────────────────────────────────
type Node =
  | { k: 'num'; v: number }
  | { k: 'param'; name: string }
  | { k: 'var'; name: string }
  | { k: 'member'; ns: string; field: string }
  | { k: 'call'; name: string; args: Node[] }
  | { k: 'unary'; op: string; e: Node }
  | { k: 'bin'; op: string; l: Node; r: Node }

class Parser {
  private p = 0
  constructor(private toks: Tok[]) {}

  private peek() { return this.toks[this.p] }
  private next() { return this.toks[this.p++] }
  private expect(t: Tok['t']) {
    const tk = this.next()
    if (!tk || tk.t !== t) throw new Error(`语法错误：期望 ${t}，实际得到 ${tk ? JSON.stringify(tk) : '结尾'}`)
  }

  parse(): Node {
    const n = this.expr()
    if (this.p < this.toks.length) throw new Error('语法错误：表达式末尾存在多余符号')
    return n
  }

  // orExpr -> andExpr ( '||' andExpr )*
  private expr(): Node { return this.orExpr() }
  private orExpr(): Node {
    let l = this.andExpr()
    while (this.peek()?.t === 'op' && (this.peek() as any).v === '||') {
      this.next(); const r = this.andExpr(); l = { k: 'bin', op: '||', l, r }
    }
    return l
  }
  private andExpr(): Node {
    let l = this.cmpExpr()
    while (this.peek()?.t === 'op' && (this.peek() as any).v === '&&') {
      this.next(); const r = this.cmpExpr(); l = { k: 'bin', op: '&&', l, r }
    }
    return l
  }
  private cmpExpr(): Node {
    let l = this.addExpr()
    const ops = ['>', '<', '>=', '<=', '==', '!=']
    while (this.peek()?.t === 'op' && ops.includes((this.peek() as any).v)) {
      const op = (this.next() as any).v; const r = this.addExpr(); l = { k: 'bin', op, l, r }
    }
    return l
  }
  private addExpr(): Node {
    let l = this.mulExpr()
    while (this.peek()?.t === 'op' && ['+', '-'].includes((this.peek() as any).v)) {
      const op = (this.next() as any).v; const r = this.mulExpr(); l = { k: 'bin', op, l, r }
    }
    return l
  }
  private mulExpr(): Node {
    let l = this.unary()
    while (this.peek()?.t === 'op' && ['*', '/', '%'].includes((this.peek() as any).v)) {
      const op = (this.next() as any).v; const r = this.unary(); l = { k: 'bin', op, l, r }
    }
    return l
  }
  private unary(): Node {
    if (this.peek()?.t === 'op' && ['-', '!'].includes((this.peek() as any).v)) {
      const op = (this.next() as any).v; return { k: 'unary', op, e: this.unary() }
    }
    return this.primary()
  }
  private primary(): Node {
    const tk = this.peek()
    if (!tk) throw new Error('语法错误：表达式不完整')
    if (tk.t === 'num') { this.next(); return { k: 'num', v: tk.v } }
    if (tk.t === 'param') { this.next(); return { k: 'param', name: tk.v } }
    if (tk.t === 'lp') { this.next(); const e = this.expr(); this.expect('rp'); return e }
    if (tk.t === 'id') {
      this.next()
      // KDJ.K 这类成员访问（命名空间.字段，无参）
      if (this.peek()?.t === 'dot') {
        this.next()
        const f = this.next()
        if (f?.t !== 'id') throw new Error(`语法错误：命名空间后应为字段名（如 KDJ.K）`)
        return { k: 'member', ns: tk.v, field: f.v }
      }
      // 函数调用
      if (this.peek()?.t === 'lp') {
        this.next()
        const args: Node[] = []
        if (this.peek()?.t !== 'rp') {
          args.push(this.expr())
          while (this.peek()?.t === 'comma') { this.next(); args.push(this.expr()) }
        }
        this.expect('rp')
        return { k: 'call', name: tk.v, args }
      }
      return { k: 'var', name: tk.v }
    }
    throw new Error(`语法错误：意外的符号 ${JSON.stringify(tk)}`)
  }
}

// ─── 序列求值原语 ──────────────────────────────────────────────────────
interface Val { values: (number | null)[]; isBool: boolean }
const seriesOf = (arr: (number | null)[]) => ({ values: arr, isBool: false })
const boolOf = (arr: (number | null)[]) => ({ values: arr, isBool: true })

function broadcast(v: Val, len: number): (number | null)[] {
  if (v.values.length === len) return v.values
  // 标量：所有位置相同
  const fill = v.values[0]
  return new Array(len).fill(fill)
}

// ─── 指标计算（复用 worker 算法，保证与内置指标一致）──────────────────
function calcMA(x: (number | null)[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(x.length).fill(null)
  let sum = 0
  for (let i = 0; i < x.length; i++) {
    const v = x[i]
    if (v == null) { sum = 0; continue }
    sum += v
    if (i >= period) sum -= x[i - period] as number
    if (i >= period - 1) out[i] = sum / period
  }
  return out
}
function calcEMA(x: (number | null)[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(x.length).fill(null)
  const k = 2 / (period + 1)
  let prev: number | null = null
  for (let i = 0; i < x.length; i++) {
    const v = x[i]
    if (v == null) continue
    prev = prev == null ? v : (v - prev) * k + prev
    out[i] = prev
  }
  return out
}
function calcRSI(x: (number | null)[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(x.length).fill(null)
  let gains = 0, losses = 0
  for (let i = 1; i < x.length; i++) {
    const v = x[i], pv = x[i - 1]
    if (v == null || pv == null) continue
    const change = v - pv
    if (i <= period) {
      if (change > 0) gains += change; else losses -= change
      if (i === period) {
        const ag = gains / period, al = losses / period
        const rs = al === 0 ? 100 : ag / al
        out[i] = 100 - 100 / (1 + rs)
      }
    } else {
      const prevRsi = out[i - 1]
      const prevAvgGain = prevRsi != null ? (100 / (100 - prevRsi) - 1) * (losses / period) : gains / period
      const prevAvgLoss = losses / period
      if (change > 0) { gains = (prevAvgGain * (period - 1) + change) / period; losses = (prevAvgLoss * (period - 1)) / period }
      else { gains = (prevAvgGain * (period - 1)) / period; losses = (prevAvgLoss * (period - 1) - change) / period }
      const rs = losses === 0 ? 100 : gains / losses
      out[i] = 100 - 100 / (1 + rs)
    }
  }
  return out
}
function calcMACD(closes: (number | null)[], fast: number, slow: number, signal: number) {
  const kf = 2 / (fast + 1), ks = 2 / (slow + 1), ksig = 2 / (signal + 1)
  const diff: (number | null)[] = new Array(closes.length).fill(null)
  const dea: (number | null)[] = new Array(closes.length).fill(null)
  const hist: (number | null)[] = new Array(closes.length).fill(null)
  let fe = 0, se = 0
  for (let i = 0; i < closes.length; i++) {
    const v = closes[i]; if (v == null) continue
    fe = i === 0 ? v : (v - fe) * kf + fe
    se = i === 0 ? v : (v - se) * ks + se
    const d = fe - se
    const prevDea = dea[i - 1]
    const curDea = prevDea == null ? d : (d - prevDea) * ksig + prevDea
    diff[i] = d; dea[i] = curDea; hist[i] = d - curDea
  }
  return { diff, dea, hist }
}
function calcKDJ(highs: (number | null)[], lows: (number | null)[], closes: (number | null)[], p: number, ks: number, ds: number) {
  const K: (number | null)[] = new Array(highs.length).fill(null)
  const D: (number | null)[] = new Array(highs.length).fill(null)
  const J: (number | null)[] = new Array(highs.length).fill(null)
  for (let i = 0; i < closes.length; i++) {
    if (i < p - 1 || highs[i] == null || lows[i] == null || closes[i] == null) continue
    let hh = -Infinity, ll = Infinity
    for (let j = 0; j < p; j++) { hh = Math.max(hh, highs[i - j] as number); ll = Math.min(ll, lows[i - j] as number) }
    const rsv = hh === ll ? 50 : ((closes[i] as number - ll) / (hh - ll)) * 100
    const prevK = K[i - 1] ?? 50, prevD = D[i - 1] ?? 50
    const k = (2 / ks) * prevK + (1 / ks) * rsv
    const d = (2 / ds) * prevD + (1 / ds) * k
    K[i] = k; D[i] = d; J[i] = 3 * k - 2 * d
  }
  return { K, D, J }
}
function calcBOLL(x: (number | null)[], period: number, mult: number) {
  const mid: (number | null)[] = new Array(x.length).fill(null)
  const upper: (number | null)[] = new Array(x.length).fill(null)
  const lower: (number | null)[] = new Array(x.length).fill(null)
  for (let i = 0; i < x.length; i++) {
    if (i < period - 1 || x[i] == null) continue
    let sum = 0
    for (let j = 0; j < period; j++) sum += x[i - j] as number
    const ma = sum / period
    let varc = 0
    for (let j = 0; j < period; j++) varc += Math.pow((x[i - j] as number) - ma, 2)
    const sd = Math.sqrt(varc / period)
    mid[i] = ma; upper[i] = ma + mult * sd; lower[i] = ma - mult * sd
  }
  return { mid, upper, lower }
}
function rollingExtreme(x: (number | null)[], period: number, kind: 'max' | 'min'): (number | null)[] {
  const out: (number | null)[] = new Array(x.length).fill(null)
  for (let i = 0; i < x.length; i++) {
    if (i < period - 1 || x[i] == null) continue
    let acc: number | null = null
    for (let j = 0; j < period; j++) {
      const v = x[i - j]
      if (v == null) { acc = null; break }
      acc = acc == null ? v : (kind === 'max' ? Math.max(acc, v) : Math.min(acc, v))
    }
    out[i] = acc
  }
  return out
}

// ─── 语义校验（供 validate 在解析后检查未知符号）──────────────────────
const KNOWN_FIELDS = new Set(['OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME', 'VOL'])
const KNOWN_NS: Record<string, Set<string>> = {
  KDJ: new Set(['K', 'D', 'J']),
  MACD: new Set(['DIFF', 'DEA', 'HIST']),
  BB: new Set(['UPPER', 'LOWER', 'MID']),
}
const KNOWN_FUNCS = new Set(['MA', 'SMA', 'EMA', 'RSI', 'REF', 'CROSS', 'HHV', 'LLV', 'ABS', 'SQRT', 'MAX', 'MIN'])

function semanticError(node: Node): string | null {
  switch (node.k) {
    case 'var':
      return KNOWN_FIELDS.has(node.name) ? null : `未知字段 "${node.name}"（可用: OPEN/HIGH/LOW/CLOSE/VOLUME）`
    case 'member': {
      const f = KNOWN_NS[node.ns]
      if (!f) return `未知命名空间 "${node.ns}"（可用 KDJ/MACD/BB）`
      if (!f.has(node.field)) return `${node.ns} 无字段 ${node.field}`
      return null
    }
    case 'call': {
      if (!KNOWN_FUNCS.has(node.name)) return `未知函数 "${node.name}()"`
      for (const a of node.args) {
        const e = semanticError(a)
        if (e) return e
      }
      return null
    }
    case 'unary':
      return semanticError(node.e)
    case 'bin':
      return semanticError(node.l) ?? semanticError(node.r)
    case 'num':
      return null
    case 'param':
      return null
  }
}

// ─── 求值 ──────────────────────────────────────────────────────────────
export function evaluate(expr: string, bars: CIBar[], params?: Record<string, number>): EvalResult {
  const len = bars.length
  if (len === 0) return { ok: false, isBool: false, values: [], error: '无 K 线数据' }
  try {
    const ast = new Parser(tokenize(expr)).parse()
    const closes = bars.map((b) => b.close)
    const highs = bars.map((b) => b.high)
    const lows = bars.map((b) => b.low)
    const opens = bars.map((b) => b.open)
    const vols = bars.map((b) => b.volume)
    const kdj = calcKDJ(highs, lows, closes, 9, 3, 3)
    const macd = calcMACD(closes, 12, 26, 9)
    const boll = calcBOLL(closes, 20, 2)

    const getConst = (node: Node, what: string): number => {
      const v = evalNode(node)
      const arr = broadcast(v, len)
      const allSame = arr.every((x) => x === arr[0])
      if (!allSame || v.isBool) throw new Error(`${what} 必须是常量数字（如整数周期）`)
      const n = arr[0] as number
      if (!Number.isInteger(n) || n <= 0) throw new Error(`${what} 必须是正整数`)
      return n
    }

    const evalNode = (node: Node): Val => {
      switch (node.k) {
        case 'num': return seriesOf(new Array(len).fill(node.v))
        case 'param': {
          const val = params?.[node.name]
          if (val == null || typeof val !== 'number' || Number.isNaN(val))
            throw new Error(`参数 @${node.name} 未提供（在指标参数中设置）`)
          return seriesOf(new Array(len).fill(val))
        }
        case 'var': {
          const m: Record<string, (number | null)[]> = {
            OPEN: opens, HIGH: highs, LOW: lows, CLOSE: closes, VOLUME: vols, VOL: vols,
          }
          const s = m[node.name]
          if (!s) throw new Error(`未知字段 "${node.name}"（可用: OPEN/HIGH/LOW/CLOSE/VOLUME）`)
          return seriesOf(s)
        }
        case 'member': {
          const ns = node.ns, f = node.field
          if (ns === 'KDJ') {
            const s = (kdj as any)[f]; if (!s) throw new Error(`KDJ 无字段 ${f}（可用 K/D/J）`); return seriesOf(s)
          }
          if (ns === 'MACD') {
            const s = (macd as any)[f.toLowerCase()]; if (!s) throw new Error(`MACD 无字段 ${f}（可用 DIFF/DEA/HIST）`); return seriesOf(s)
          }
          if (ns === 'BB') {
            const s = (boll as any)[f.toLowerCase()]; if (!s) throw new Error(`BB 无字段 ${f}（可用 UPPER/LOWER/MID）`); return seriesOf(s)
          }
          throw new Error(`未知命名空间 "${ns}"（可用 KDJ/MACD/BB）`)
        }
        case 'unary': {
          const e = evalNode(node.e)
          const ea = broadcast(e, len)
          if (node.op === '-') return seriesOf(ea.map((v) => (v == null ? null : -v)))
          // !
          return boolOf(ea.map((v) => (v == null ? null : v === 0 ? 1 : 0)))
        }
        case 'bin': {
          const l = broadcast(evalNode(node.l), len)
          const r = broadcast(evalNode(node.r), len)
          const op = node.op
          if (['>', '<', '>=', '<=', '==', '!='].includes(op)) {
            const out = new Array(len)
            for (let i = 0; i < len; i++) {
              const a = l[i], b = r[i]
              if (a == null || b == null) { out[i] = null; continue }
              out[i] = (
                op === '>' ? a > b : op === '<' ? a < b : op === '>=' ? a >= b :
                op === '<=' ? a <= b : op === '==' ? a === b : a !== b
              ) ? 1 : 0
            }
            return boolOf(out)
          }
          if (op === '&&' || op === '||') {
            const out = new Array(len)
            for (let i = 0; i < len; i++) {
              const a = l[i], b = r[i]
              if (a == null || b == null) { out[i] = null; continue }
              const av = a !== 0, bv = b !== 0
              out[i] = (op === '&&' ? av && bv : av || bv) ? 1 : 0
            }
            return boolOf(out)
          }
          // 算术
          const out = new Array(len)
          for (let i = 0; i < len; i++) {
            const a = l[i], b = r[i]
            if (a == null || b == null) { out[i] = null; continue }
            switch (op) {
              case '+': out[i] = a + b; break
              case '-': out[i] = a - b; break
              case '*': out[i] = a * b; break
              case '/': out[i] = b === 0 ? null : a / b; break
              case '%': out[i] = b === 0 ? null : a % b; break
            }
          }
          return seriesOf(out)
        }
        case 'call': {
          const name = node.name
          const argReq: Record<string, number> = { REF: 2, HHV: 2, LLV: 2, CROSS: 2, MAX: 2, MIN: 2, ABS: 1, SQRT: 1 }
          const req = argReq[name]
          if (req != null && node.args.length < req) throw new Error(`函数 ${name}() 需要 ${req} 个参数`)
          if (['MA', 'SMA', 'EMA', 'RSI'].includes(name) && ![1, 2].includes(node.args.length))
            throw new Error(`函数 ${name}() 需要 1 或 2 个参数（周期必填，单参时作用于 CLOSE）`)
          const a0 = node.args[0]
          const single = node.args.length === 1
          const periodNode = single ? node.args[0] : node.args[1]
          const src = single ? closes : broadcast(evalNode(a0), len)
          switch (name) {
            case 'MA':
            case 'SMA': return seriesOf(calcMA(src, getConst(periodNode, `${name} 周期`)))
            case 'EMA': return seriesOf(calcEMA(src, getConst(periodNode, `${name} 周期`)))
            case 'RSI': return seriesOf(calcRSI(src, getConst(periodNode, `${name} 周期`)))
            case 'REF': {
              const n = getConst(node.args[1], 'REF 周期'); const x = broadcast(evalNode(a0), len)
              const out = new Array(len).fill(null)
              for (let i = n; i < len; i++) out[i] = x[i - n]
              return seriesOf(out)
            }
            case 'HHV': return seriesOf(rollingExtreme(broadcast(evalNode(a0), len), getConst(node.args[1], 'HHV 周期'), 'max'))
            case 'LLV': return seriesOf(rollingExtreme(broadcast(evalNode(a0), len), getConst(node.args[1], 'LLV 周期'), 'min'))
            case 'CROSS': {
              const a = broadcast(evalNode(node.args[0]), len), b = broadcast(evalNode(node.args[1]), len)
              const out = new Array(len).fill(null)
              for (let i = 1; i < len; i++) {
                const a0v = a[i - 1], b0v = b[i - 1], a1v = a[i], b1v = b[i]
                if ([a0v, b0v, a1v, b1v].some((v) => v == null)) continue
                out[i] = (a0v as number) <= (b0v as number) && (a1v as number) > (b1v as number) ? 1 : 0
              }
              return boolOf(out)
            }
            case 'ABS': return seriesOf(broadcast(evalNode(a0), len).map((v) => (v == null ? null : Math.abs(v))))
            case 'SQRT': return seriesOf(broadcast(evalNode(a0), len).map((v) => (v == null ? null : v < 0 ? null : Math.sqrt(v))))
            case 'MAX': case 'MIN': {
              const a = broadcast(evalNode(node.args[0]), len), b = broadcast(evalNode(node.args[1]), len)
              const out = new Array(len)
              for (let i = 0; i < len; i++) out[i] = (a[i] == null || b[i] == null) ? null : (name === 'MAX' ? Math.max(a[i] as number, b[i] as number) : Math.min(a[i] as number, b[i] as number))
              return seriesOf(out)
            }
            default: throw new Error(`未知函数 "${name}()"`)
          }
        }
      }
    }

    const res = evalNode(ast)
    const values = broadcast(res, len)
    return { ok: true, isBool: res.isBool, values }
  } catch (e: any) {
    return { ok: false, isBool: false, values: [], error: e?.message ?? String(e) }
  }
}

/** 仅做语法/语义校验（不依赖 K 线数据），用于 UI 实时反馈 */
/** 提取表达式中引用的 @参数 名称（去重，按首次出现顺序），供 UI 自动生成参数编辑器 */
export function listParams(expr: string): string[] {
  try {
    const ast = new Parser(tokenize(expr)).parse()
    const set: string[] = []
    const walk = (n: Node) => {
      switch (n.k) {
        case 'param': if (!set.includes(n.name)) set.push(n.name); break
        case 'unary': walk(n.e); break
        case 'bin': walk(n.l); walk(n.r); break
        case 'call': n.args.forEach(walk); break
      }
    }
    walk(ast)
    return set
  } catch {
    return []
  }
}

export function validate(expr: string, params?: Record<string, number>): { ok: boolean; error?: string; params?: string[] } {
  try {
    const ast = new Parser(tokenize(expr)).parse()
    const err = semanticError(ast)
    if (err) return { ok: false, error: err }
    const refs = listParams(expr)
    if (params) {
      const missing = refs.filter((p) => !(p in params) || params[p] == null || Number.isNaN(params[p] as number))
      if (missing.length) return { ok: false, error: `参数 ${missing.map((m) => '@' + m).join(', ')} 未定义或为空` }
    }
    return { ok: true, params: refs }
  } catch (e: any) {
    return { ok: false, error: e?.message ?? String(e) }
  }
}

/**
 * 建议叠加方式：振荡类指标（RSI/KDJ/MACD/BB）值域有限或含负值，
 * 叠加到主图会严重扭曲价格尺度，建议置于独立副图；其余（均线等价格级）随主图。
 */
const OSC_TOKENS = ['KDJ', 'MACD', 'BB', 'RSI']
export function suggestPane(expr: string): 'overlay' | 'separate' {
  const up = expr.toUpperCase()
  return OSC_TOKENS.some((t) => up.includes(t)) ? 'separate' : 'overlay'
}

/**
 * 收集布尔表达式的所有「上穿跳变」触发点（prev != 1 且 cur == 1）。
 * 供信号日志展示与回测引擎做条件触发扫描。
 */
export function collectBoolSignals(expr: string, bars: CIBar[], params?: Record<string, number>): { ok: boolean; times: string[]; error?: string } {
  const r = evaluate(expr, bars, params)
  if (!r.ok) return { ok: false, times: [], error: r.error }
  if (!r.isBool) return { ok: true, times: [] }
  const times: string[] = []
  for (let i = 1; i < r.values.length; i++) {
    if (r.values[i] === 1 && r.values[i - 1] !== 1) times.push(bars[i].time)
  }
  return { ok: true, times }
}

/** 单笔交易明细（PROD-11 追问 G：回测交易 CSV 导出） */
export interface TradeRecord {
  /** 买入日期 */
  buyDate: string
  /** 卖出日期（未平仓则为 ''） */
  sellDate: string
  /** 买入价格 */
  buyPrice: number
  /** 卖出价格（未平仓则为 0） */
  sellPrice: number
  /** 单笔收益率 (%) */
  returnPct: number
  /** 持有天数 */
  holdingDays: number
  /** 盈亏标记 */
  win: boolean
}

/** 信号回测结果：把布尔表达式当作「条件触发」策略做事件驱动回测 */
export interface SignalBacktestResult {
  ok: boolean
  error?: string
  /** 买入（0->1 上穿）K 线日期 */
  buys: string[]
  /** 卖出（1->0 下穿）K 线日期 */
  sells: string[]
  /** 完整配对交易数 */
  trades: number
  /** 盈利交易数 */
  wins: number
  /** 胜率 (%) */
  winRate: number
  /** 累计收益率 (%)：每笔收益连乘 */
  totalReturnPct: number
  /** 最大回撤 (%) */
  maxDrawdownPct: number
  /** 末根仍持仓（未平仓） */
  holding: boolean
  /** 逐笔交易明细（PROD-11 追问 G：用于 CSV 导出与复盘） */
  tradeDetails: TradeRecord[]
}

/**
 * 轻量事件驱动回测：表达式从 0->1 上穿买入（收盘建仓），1->0 下穿卖出（收盘平仓）。
 * 假设 T 日信号 T 日收盘成交；末根若仍成立则标记为持仓（不强制平仓，避免末端失真）。
 * 直接复用 evaluate，与图表、信号日志同源，可作为回测引擎的条件触发入口。
 */
export function runSignalBacktest(expr: string, bars: CIBar[], params?: Record<string, number>): SignalBacktestResult {
  const empty = (error?: string): SignalBacktestResult => ({
    ok: false, error, buys: [], sells: [], trades: 0, wins: 0,
    winRate: 0, totalReturnPct: 0, maxDrawdownPct: 0, holding: false,
    tradeDetails: [],
  })
  const r = evaluate(expr, bars, params)
  if (!r.ok) return empty(r.error)
  if (!r.isBool) return empty('仅支持布尔表达式（如 CROSS(...) 或 比较运算），数值序列无触发点')
  if (bars.length < 2) return empty('K 线数量不足')

  const v = r.values
  const buys: string[] = []
  const sells: string[] = []
  let trades = 0, wins = 0
  let entry: number | null = null
  let entryDate = ''
  let entryPrice = 0
  let equity = 1, peak = 1, maxDd = 0
  const tradeDetails: TradeRecord[] = []

  for (let i = 1; i < v.length; i++) {
    if (v[i] == null || v[i - 1] == null) continue // 预热期跳过
    const cur = v[i] as number
    const prev = v[i - 1] as number
    if (cur === 1 && prev !== 1) {
      // 上穿：买入（若已空仓）
      buys.push(bars[i].time)
      if (entry == null) {
        entry = bars[i].close
        entryDate = bars[i].time
        entryPrice = bars[i].close
      }
    } else if (cur !== 1 && prev === 1) {
      // 下穿：卖出（若持仓）
      sells.push(bars[i].time)
      if (entry != null) {
        const ret = bars[i].close / entry - 1
        // 计算持有天数（从 entryDate 到 bars[i].time 的日历日差）
        const buyD = new Date(entryDate.replace(' ', 'T'))
        const sellD = new Date(bars[i].time.replace(' ', 'T'))
        const holdingDays = Math.max(1, Math.round((sellD.getTime() - buyD.getTime()) / 86400000))
        tradeDetails.push({
          buyDate: entryDate,
          sellDate: bars[i].time,
          buyPrice: entryPrice,
          sellPrice: bars[i].close,
          returnPct: ret * 100,
          holdingDays,
          win: ret > 0,
        })
        trades++
        if (ret > 0) wins++
        equity *= 1 + ret
        if (equity > peak) peak = equity
        const dd = peak > 0 ? (peak - equity) / peak : 0
        if (dd > maxDd) maxDd = dd
        entry = null
      }
    }
  }

  // 若末根仍持仓，记录未平仓明细
  if (entry != null) {
    const lastBar = bars[bars.length - 1]
    const ret = lastBar.close / entryPrice - 1
    const buyD = new Date(entryDate.replace(' ', 'T'))
    const lastD = new Date(lastBar.time.replace(' ', 'T'))
    const holdingDays = Math.max(1, Math.round((lastD.getTime() - buyD.getTime()) / 86400000))
    tradeDetails.push({
      buyDate: entryDate,
      sellDate: '',
      buyPrice: entryPrice,
      sellPrice: 0,
      returnPct: ret * 100,
      holdingDays,
      win: ret > 0,
    })
  }

  return {
    ok: true,
    buys,
    sells,
    trades,
    wins,
    winRate: trades > 0 ? (wins / trades) * 100 : 0,
    totalReturnPct: (equity - 1) * 100,
    maxDrawdownPct: maxDd * 100,
    holding: entry != null,
    tradeDetails,
  }
}

/**
 * 把自定义布尔表达式接入「真实策略回测引擎」：复用 evaluate 的事件驱动逻辑，
 * 生成与后端 /backtest/run 完全兼容的 BacktestResult 结构
 * （equity_curve / trades / metrics），可直接喂给回测 Tear Sheet / 权益曲线 / 水下图 / 交易明细。
 * 与 runSignalBacktest 的区别：本函数输出引擎渲染所需全套字段，而非单纯统计指标。
 */
export interface CustomExprBacktestResult {
  equity_curve: { equity: number; strategy: number; date: string; benchmark: number }[]
  trades: { date: string; action: 'BUY' | 'SELL'; profit: number }[]
  metrics: {
    total_return: string
    annualized_return: string
    sharpe_ratio: string
    max_drawdown: string
    win_rate: string
    total_trades: number
    profit_factor: string
    total_friction_cost: string
  }
}

export function runCustomExprBacktest(
  expr: string,
  bars: CIBar[],
  initialCapital = 100000,
  params?: Record<string, number>,
): { ok: boolean; error?: string; result?: CustomExprBacktestResult; dailyReturns: number[] } {
  const r = evaluate(expr, bars, params)
  if (!r.ok) return { ok: false, error: r.error, dailyReturns: [] }
  if (!r.isBool) return { ok: false, error: '仅支持布尔表达式作为回测信号（如 CROSS(MA(CLOSE,5), MA(CLOSE,20)) 或 RSI(14) > 70）', dailyReturns: [] }
  if (bars.length < 2) return { ok: false, error: 'K 线数量不足', dailyReturns: [] }

  const v = r.values
  const equity_curve: CustomExprBacktestResult['equity_curve'] = []
  const trades: CustomExprBacktestResult['trades'] = []
  let cash = initialCapital
  let shares = 0
  let entryPrice = 0
  let wins = 0
  let grossProfit = 0
  let grossLoss = 0
  const benchmarkShares = initialCapital / bars[0].close
  let prevEquity = initialCapital
  const dailyReturns: number[] = []

  for (let i = 0; i < v.length; i++) {
    const cur = v[i] as number
    const prev = i > 0 && v[i - 1] != null ? (v[i - 1] as number) : 0
    if (cur === 1 && prev !== 1 && shares === 0) {
      // 上穿：整仓买入
      shares = cash / bars[i].close
      cash = 0
      entryPrice = bars[i].close
      trades.push({ date: bars[i].time, action: 'BUY', profit: 0 })
    } else if (cur !== 1 && prev === 1 && shares > 0) {
      // 下穿：整仓卖出（profit 为该笔绝对金额，美元）
      const exitPrice = bars[i].close
      cash = shares * exitPrice
      const profit = (exitPrice - entryPrice) * shares
      if (profit > 0) { wins++; grossProfit += profit } else grossLoss += Math.abs(profit)
      trades.push({ date: bars[i].time, action: 'SELL', profit })
      shares = 0
      entryPrice = 0
    }
    const eq = cash + shares * bars[i].close
    const bench = benchmarkShares * bars[i].close
    equity_curve.push({ equity: eq, strategy: eq, date: bars[i].time, benchmark: bench })
    if (i > 0) dailyReturns.push(eq / prevEquity - 1)
    prevEquity = eq
  }

  const finalEquity = cash + shares * bars[bars.length - 1].close
  const totalReturn = (finalEquity / initialCapital - 1) * 100
  const annualized = (Math.pow(finalEquity / initialCapital, 252 / Math.max(bars.length - 1, 1)) - 1) * 100
  const mean = dailyReturns.reduce((a, b) => a + b, 0) / Math.max(dailyReturns.length, 1)
  const variance = dailyReturns.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(dailyReturns.length - 1, 1)
  const sharpe = variance > 0 ? (mean / Math.sqrt(variance)) * Math.sqrt(252) : 0
  let procMax = initialCapital
  let maxDd = 0
  for (const p of equity_curve) {
    if (p.equity > procMax) procMax = p.equity
    const dd = (procMax - p.equity) / procMax
    if (dd > maxDd) maxDd = dd
  }
  const totalTrades = trades.filter((t) => t.action === 'SELL').length
  const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? 999 : 0

  const metrics: CustomExprBacktestResult['metrics'] = {
    total_return: `${totalReturn.toFixed(2)}%`,
    annualized_return: `${annualized.toFixed(2)}%`,
    sharpe_ratio: sharpe.toFixed(2),
    max_drawdown: `-${maxDd.toFixed(2)}%`,
    win_rate: `${winRate.toFixed(1)}%`,
    total_trades: totalTrades,
    profit_factor: profitFactor.toFixed(2),
    total_friction_cost: '$0.00',
  }

  return { ok: true, result: { equity_curve, trades, metrics }, dailyReturns }
}

/**
 * 参数网格搜索（PROD-11 追问6）：对含 @参数 的自定义表达式，在给定参数区间内做笛卡尔积穷举，
 * 逐组复用 runCustomExprBacktest 计算回测指标，按选定指标排序返回 Top-N，供 UI 一键「应用最优参数」。
 * 与图表/信号/回测同源（均走 evaluate），零新增数据依赖。组合数上限保护，避免浏览器卡死。
 */
export interface ParamGridSpec {
  min: number
  max: number
  step: number
}
export interface ParamGrid {
  [name: string]: ParamGridSpec
}
export interface GridSearchMetrics {
  /** 累计收益率 (%) */
  totalReturnPct: number
  /** 年化夏普比率 */
  sharpe: number
  /** 胜率 (%) */
  winRatePct: number
  /** 最大回撤幅度 (%)，取绝对值，越小越好 */
  maxDrawdownPct: number
  /** 完整交易数 */
  trades: number
}
export interface GridSearchItem {
  params: Record<string, number>
  ok: boolean
  error?: string
  metrics?: GridSearchMetrics
}
export type GridSortBy = 'totalReturnPct' | 'sharpe' | 'winRatePct' | 'maxDrawdownPct'
export interface ParamGridSearchResult {
  ok: boolean
  error?: string
  /** 笛卡尔积生成的参数组合数 */
  total: number
  /** 实际跑完的组数（剔除非法/非布尔组合后） */
  ran: number
  /** 已排序（按 sortBy 降序；maxDrawdownPct 为升序，越小越好）的 Top-N */
  items: GridSearchItem[]
  /** 全局最优一组 */
  best?: GridSearchItem
}

const MAX_GRID_COMBOS = 1000

export function runParamGridSearch(
  expr: string,
  bars: CIBar[],
  grid: ParamGrid,
  opts?: { initialCapital?: number; sortBy?: GridSortBy; limit?: number },
): ParamGridSearchResult {
  const names = Object.keys(grid)
  if (names.length === 0)
    return { ok: false, error: '未提供参数网格（表达式需包含 @参数，如 @period）', total: 0, ran: 0, items: [] }
  if (bars.length < 2)
    return { ok: false, error: 'K 线数量不足，无法回测', total: 0, ran: 0, items: [] }

  // 笛卡尔积：每个参数按 min/max/step 展开为整数步进序列（避免浮点累积误差）
  const ranges = names.map((n) => {
    const g = grid[n]
    const step = g.step > 0 ? g.step : 1
    const arr: number[] = []
    let v = g.min
    let guard = 0
    while (v <= g.max + 1e-9 && guard < 100000) {
      arr.push(Math.round(v * 1e6) / 1e6)
      v += step
      guard++
    }
    if (arr.length === 0) arr.push(g.min)
    return arr
  })
  let combos: Record<string, number>[] = [{}]
  for (let i = 0; i < names.length; i++) {
    const next: Record<string, number>[] = []
    for (const base of combos) for (const val of ranges[i]) next.push({ ...base, [names[i]]: val })
    combos = next
  }
  if (combos.length > MAX_GRID_COMBOS)
    return { ok: false, error: `组合数过大（${combos.length}），请调大 step 或缩小范围（上限 ${MAX_GRID_COMBOS}）`, total: combos.length, ran: 0, items: [] }

  const items: GridSearchItem[] = []
  for (const params of combos) {
    const r = runCustomExprBacktest(expr, bars, opts?.initialCapital ?? 100000, params)
    if (!r.ok || !r.result) {
      items.push({ params, ok: false, error: r.error })
      continue
    }
    const m = r.result.metrics
    items.push({
      params,
      ok: true,
      metrics: {
        totalReturnPct: parseFloat(m.total_return),
        sharpe: parseFloat(m.sharpe_ratio),
        winRatePct: parseFloat(m.win_rate),
        maxDrawdownPct: Math.abs(parseFloat(m.max_drawdown)),
        trades: m.total_trades,
      },
    })
  }

  const sortBy: GridSortBy = opts?.sortBy ?? 'totalReturnPct'
  const sorted = items.slice().sort((a, b) => {
    if (a.ok !== b.ok) return a.ok ? -1 : 1
    if (!a.ok || !b.ok || !a.metrics || !b.metrics) return 0
    const av = a.metrics[sortBy]
    const bv = b.metrics[sortBy]
    // 回撤：幅度越小越好 → 升序；其余：越大越好 → 降序
    return sortBy === 'maxDrawdownPct' ? av - bv : bv - av
  })

  const limit = opts?.limit ?? 50
  return { ok: true, total: combos.length, ran: items.length, items: sorted.slice(0, limit), best: sorted[0] }
}
