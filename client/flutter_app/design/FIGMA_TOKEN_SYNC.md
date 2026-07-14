# Figma Variables → Dart Token 同步表（CLI-ARCH-02）

> **SSOT 代码**：`lib/presentation/theme/color_tokens.dart`  
> **机器可读表**：`design/figma_variables_sync.json`  
> **规范**：`docs/05` §七 / §八

## 色板 · Color/Semantic（Dark）

| Figma Variable | Dart | Hex | Web 对齐 | 语义 |
|:---|:---|:---|:---|:---|
| `Color/Semantic/bull` | `AppColors.bull` | `#10B981` | emerald-500 | 涨 / 多 / 盈利 |
| `Color/Semantic/bear` | `AppColors.bear` | `#EF4444` | red-500 | 跌 / 空 / 亏损 |
| `Color/Semantic/warn` | `AppColors.warn` | `#F59E0B` | amber-500 | 警告 / STALE |
| `Color/Semantic/primary` | `AppColors.primary` | `#8B5CF6` | violet-500 | 主交互 |
| `Color/Semantic/bgPrimary` | `AppColors.bgPrimary` | `#09090B` | zinc-950 | 背景 |
| `Color/Semantic/bgCard` | `AppColors.bgCard` | `#18181B` | zinc-900 | 卡片 |
| `Color/Semantic/label` | `AppColors.label` | `#94A3B8` | slate-400 | 次要文字 |
| `Color/Semantic/onSurface` | `AppColors.onSurface` | `#F8FAFC` | slate-50 | 主文字 |
| `Color/Semantic/border` | `AppColors.border` | `#FFFFFF` @ 10% | white/10 | 边框 |

## 间距 · Space（4px 栅格）

| Figma | Dart | px |
|:---|:---|---:|
| `Space/1` | `AppSpace.s1` | 4 |
| `Space/2` | `AppSpace.s2` | 8 |
| `Space/3` | `AppSpace.s3` | 12 |
| `Space/4` | `AppSpace.s4` | 16 |
| `Space/6` | `AppSpace.s6` | 24 |

## 圆角 · Radius

| Figma | Dart | px |
|:---|:---|---:|
| `Radius/sm` | `AppRadius.sm` | 8 |
| `Radius/md` | `AppRadius.md` | 12 |
| `Radius/lg` | `AppRadius.lg` | 16 |

## 同步流程

1. 设计师在 Figma **Variables** 改 `Color/Semantic`（禁止组件绑 Raw）  
2. 导出 / 手改 `design/figma_variables_sync.json`  
3. 对齐 `color_tokens.dart` 常量  
4. `flutter test test/cli_arch02_figma_token_sync_test.dart` 必须绿  

**禁止**：在 Feature Widget 内硬编码 `#RRGGBB`（应用 `AppColors.*`）。
