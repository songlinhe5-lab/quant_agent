import { useState, useEffect } from 'react'

/**
 * React 版本的中文相对时间 Hook
 * @param time Date 对象、时间戳或 ISO 时间字符串
 * @returns 响应式的相对时间字符串 (如 "刚刚", "5 分钟前")
 */
export function useZhTimeAgo(time: Date | number | string | null | undefined): string {
  const [timeAgo, setTimeAgo] = useState('')

  useEffect(() => {
    if (!time) {
      setTimeAgo('')
      return
    }

    const updateTime = () => {
      const now = new Date()
      const past = new Date(time)
      const diffMs = now.getTime() - past.getTime()
      const diffSec = Math.floor(diffMs / 1000)
      const diffMin = Math.floor(diffSec / 60)
      const diffHour = Math.floor(diffMin / 60)
      const diffDay = Math.floor(diffHour / 24)

      if (diffSec < 60) setTimeAgo('刚刚')
      else if (diffMin < 60) setTimeAgo(`${diffMin} 分钟前`)
      else if (diffHour < 24) setTimeAgo(`${diffHour} 小时前`)
      else if (diffDay < 30) setTimeAgo(`${diffDay} 天前`)
      else setTimeAgo(past.toLocaleDateString('zh-CN'))
    }

    updateTime()
    // 每 60 秒自动刷新一次视图
    const interval = setInterval(updateTime, 60000)
    return () => clearInterval(interval)
  }, [time])

  return timeAgo
}
