import { create } from 'zustand'

/** 资产类型：对话导出 / 首席报告 */
export type AssetType = 'chat' | 'chief'

export interface AssetItem {
  id: string
  type: AssetType
  title: string
  /** 来源会话（对话标题或投研会命题） */
  source: string
  date: string
  /** Markdown 内容（只读预览用） */
  content: string
}

const STORAGE_KEY = 'quant_asset_library'

function load(): AssetItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function save(items: AssetItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
  } catch {
    /* 忽略存储失败 */
  }
}

interface AssetLibraryState {
  items: AssetItem[]
  /** 存档一项资产（去重：同 title+content 不重复添加） */
  addAsset: (a: Omit<AssetItem, 'id' | 'date'>) => string | null
  removeAsset: (id: string) => void
}

/**
 * COPILOT-18: B2 资产库（后端落库前的本地存档）。
 * 数据源：对话导出(升级为同时存档) + 首席报告存档。
 * 后端落库后可切到 HTTP 接口，UI 层数据结构不变。
 */
export const useAssetLibrary = create<AssetLibraryState>((set, get) => ({
  items: load(),
  addAsset: (a) => {
    const { items } = get()
    // 去重：同类型+标题+内容已存在则不重复添加
    const dup = items.some((x) => x.type === a.type && x.title === a.title && x.content === a.content)
    if (dup) return null
    const item: AssetItem = {
      ...a,
      id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      date: new Date().toISOString(),
    }
    const next = [item, ...items]
    set({ items: next })
    save(next)
    return item.id
  },
  removeAsset: (id) => {
    const next = get().items.filter((x) => x.id !== id)
    set({ items: next })
    save(next)
  },
}))
