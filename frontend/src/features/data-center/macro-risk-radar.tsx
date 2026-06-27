import React from 'react';
import { Radio, Info } from 'lucide-react';
import { RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer, Tooltip } from 'recharts';
import { useTheme } from 'next-themes';
import { RadarInfoPanel } from './event-panels';

export function MacroRiskRadar({ radar, radarInfo, setRadarInfo }: { radar: any[], radarInfo: boolean, setRadarInfo: (v: boolean) => void }) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  
  return (
    <div className="glass-card rounded-lg overflow-hidden relative">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <Radio className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">宏观风险雷达</span>
        <button onClick={() => setRadarInfo(true)} className="ml-auto flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground bg-secondary/30 hover:bg-secondary/60 px-2 py-0.5 rounded-full">
          <Info className="h-3 w-3" /><span>算法</span>
        </button>
      </div>
      {radarInfo && <RadarInfoPanel radarData={radar} onClose={() => setRadarInfo(false)} />}
      <div className="p-1 h-44">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={radar}>
            <PolarGrid stroke={isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)"} />
            <PolarAngleAxis dataKey="axis" tick={{ fill: isDark ? 'rgba(156,163,175,0.8)' : 'rgba(100,116,139,0.8)', fontSize: 10 }} />
            <Radar name="当前" dataKey="current" stroke={isDark ? "#0ecb81" : "#059669"} fill={isDark ? "#0ecb81" : "#059669"} fillOpacity={0.15} strokeWidth={1.5} isAnimationActive={true} animationDuration={1200} animationEasing="ease-out" />
            <Radar name="基准" dataKey="benchmark" stroke={isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.25)"} fill={isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.03)"} strokeWidth={1} strokeDasharray="4 2" isAnimationActive={true} animationDuration={1200} animationEasing="ease-out" />
            <Tooltip contentStyle={{ background: isDark ? 'oklch(0.18 0.01 270)' : 'rgba(255, 255, 255, 0.95)', border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)', borderRadius: '6px', fontSize: 11 }} labelStyle={{ color: isDark ? 'rgba(156,163,175,1)' : 'rgba(100,116,139,1)' }} itemStyle={{ color: isDark ? 'white' : 'black' }} />
          </RadarChart>
        </ResponsiveContainer>
      </div>
      <div className="px-4 py-1.5 border-t border-border/20 flex items-center gap-4 text-[10px]">
        <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-[#059669] dark:bg-[#0ecb81] rounded" />当前</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 border-t border-dashed border-muted-foreground/50" />基准</span>
        <span className="ml-auto text-[9px] text-muted-foreground italic">{'>'}70=乐观</span>
      </div>
    </div>
  );
}