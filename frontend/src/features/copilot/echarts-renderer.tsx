"use client"

import React, { useEffect, useRef } from 'react';
import * as echarts from 'echarts';

interface EChartsRendererProps {
  options: any;
}

export function EChartsRenderer({ options }: EChartsRendererProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (chartRef.current) {
      // 初始化 ECharts 实例，并默认采用暗黑模式优化
      chartInstance.current = echarts.init(chartRef.current);

      // 监听窗口缩放事件，动态重绘图表大小
      const handleResize = () => chartInstance.current?.resize();
      window.addEventListener('resize', handleResize);

      return () => {
        chartInstance.current?.dispose();
        window.removeEventListener('resize', handleResize);
      };
    }
  }, []);

  // 监听大模型流式输出过程中 options 的变化并无缝更新图表
  useEffect(() => {
    if (chartInstance.current && options) {
      chartInstance.current.setOption(options, true);
    }
  }, [options]);

  return <div ref={chartRef} className="w-full h-[350px]" />;
}