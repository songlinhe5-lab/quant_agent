import { useEffect, useRef } from 'react'
import { INDICATOR_WORKER_CODE } from '@/workers/indicator-worker-code'

export function useIndicatorWorker() {
  const workerRef = useRef<Worker | null>(null)

  useEffect(() => {
    let workerUrl = ''
    // 利用 Blob 动态加载彻底免除 Webpack 的跨文件打包配置干扰
    if (typeof window !== 'undefined') {
      const blob = new Blob([INDICATOR_WORKER_CODE], { type: 'application/javascript' })
      workerUrl = URL.createObjectURL(blob)
      workerRef.current = new Worker(workerUrl)
    }
    return () => {
      if (workerRef.current) {
        workerRef.current.terminate()
        workerRef.current = null
      }
      if (workerUrl) URL.revokeObjectURL(workerUrl)
    }
  }, [])

  return workerRef
}