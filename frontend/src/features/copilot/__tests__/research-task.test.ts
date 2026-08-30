import { describe, expect, it } from 'vitest'
import { isNewResearchTask } from '@/features/copilot/chat-stream-service'

describe('isNewResearchTask（RESEARCH-01 新投研任务识别）', () => {
  it('命中：完整新投研指令（深度研判）', () => {
    expect(isNewResearchTask('请对 阅文集团 进行深度研判，综合基本面、技术面和估值，给出投资建议。')).toBe(true)
  })

  it('命中：深度调研 / 投研 变体', () => {
    expect(isNewResearchTask('对 AAPL 做一次深度调研')).toBe(true)
    expect(isNewResearchTask('投研看看这个标的')).toBe(true)
  })

  it('排除：同一话题的追问（再/继续/接着/补充/追问 开头）', () => {
    expect(isNewResearchTask('再深度研判一下 AAPL 的估值')).toBe(false)
    expect(isNewResearchTask('继续分析阅文的估值')).toBe(false)
    expect(isNewResearchTask('接着上次的调研继续')).toBe(false)
  })

  it('排除：普通对话不含投研指令词', () => {
    expect(isNewResearchTask('你好，帮我看看今天的市场')).toBe(false)
    expect(isNewResearchTask('这个策略回测结果如何？')).toBe(false)
  })
})
