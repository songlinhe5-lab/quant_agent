import { createContext, useContext } from 'react'

/**
 * Keep-Alive 激活态上下文：告知被缓存（隐藏但未卸载）的模块当前是否为激活路由。
 * WS / 轮询等副作用应据此在后台模块中暂停，避免多模块 WS 并发重连风暴。
 *
 * 独立成文件，避免与 KeepAliveOutlet 组件同文件导出导致的 fast-refresh 警告。
 */
export const KeepAliveActiveContext = createContext<boolean>(true)

export const useKeepAliveActive = () => useContext(KeepAliveActiveContext)
