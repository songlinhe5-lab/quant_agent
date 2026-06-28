'use client'

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import zhCN from '@/locales/zh.json'
import enUS from '@/locales/en.json'

// 语言包映射
const locales = {
  'zh-CN': zhCN,
  'en-US': enUS,
} as const

export type Locale = keyof typeof locales
export type LocaleValue = typeof locales[Locale]

// 递归获取嵌套键值
type NestedKeyOf<T, Prefix extends string = ''> = T extends object
  ? {
      [K in keyof T & string]: T[K] extends object
        ? NestedKeyOf<T[K], `${Prefix}${K}.`>
        : `${Prefix}${K}`
    }[keyof T & string]
  : never

export type DictionaryKey = NestedKeyOf<LocaleValue>

// 简化的翻译函数（支持嵌套键）
function getNestedValue(obj: Record<string, unknown>, path: string): string {
  const keys = path.split('.')
  let current: unknown = obj
  
  for (const key of keys) {
    if (current === null || current === undefined) return path
    current = (current as Record<string, unknown>)[key]
  }
  
  return typeof current === 'string' ? current : path
}

interface I18nContextType {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: string, params?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nContextType | undefined>(undefined)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>('zh-CN')

  useEffect(() => {
    // 从 localStorage 恢复
    const savedLocale = localStorage.getItem('app_locale') as Locale
    if (savedLocale && locales[savedLocale]) {
      setLocaleState(savedLocale)
      return
    }
    
    // 检测浏览器语言
    const browserLang = navigator.language
    if (browserLang.startsWith('zh')) {
      setLocaleState('zh-CN')
    } else {
      setLocaleState('en-US')
    }
  }, [])

  const setLocale = (newLocale: Locale) => {
    setLocaleState(newLocale)
    localStorage.setItem('app_locale', newLocale)
  }

  const t = (key: string, params?: Record<string, string | number>): string => {
    const dict = locales[locale] || locales['zh-CN']
    let value = getNestedValue(dict as unknown as Record<string, unknown>, key)
    
    // 参数替换
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        value = value.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
      })
    }
    
    return value
  }

  return <I18nContext.Provider value={{ locale, setLocale, t }}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n 必须在 I18nProvider 内部使用')
  return context
}