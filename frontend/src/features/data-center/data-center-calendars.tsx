import { CalendarsModule } from '@/features/calendars/module'

// 宏观日历 tab 的所有子面板（FRED 宏观图表 / FedWatch 利率路径 / 财经快讯 等）已统一收编到
// CalendarsModule 内部的子 tab 体系（对齐 Figma 设计稿 8 子 tab 布局）。
// 本组件仅作为入口渲染 CalendarsModule，不再单独承载任何子面板。
export function CalendarsTab() {
  return <CalendarsModule />
}
