import React, { useState, useEffect } from 'react'

export const ThinkTimer = ({ startTime, endTime }: { startTime: number, endTime?: number }) => {
  const [now, setNow] = useState(endTime || Date.now())
  useEffect(() => {
    if (endTime) {
      setNow(endTime)
      return
    }
    const timer = setInterval(() => {
      if (!document.hidden) setNow(Date.now())
    }, 100)
    return () => clearInterval(timer)
  }, [endTime])
  
  const duration = Math.max(0, (now - startTime) / 1000)
  return <span>用时 {duration.toFixed(1)}s</span>
}