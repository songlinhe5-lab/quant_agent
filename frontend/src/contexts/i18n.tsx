'use client'

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react'

export const dictionaries = {
  'zh-CN': {
    settings: '设置',
    language: '语言',
    system_language: '系统语言',
    theme: '主题模式',
    dark_mode: '深色',
    light_mode: '浅色',
    english: 'English',
    chinese: '简体中文',
    logout: '退出登录',
    // 新闻标签
    FED: '美联储',
    ECB: '欧央行',
    BOJ: '日央行',
    INFLATION: '通胀',
    ECONOMY: '宏观',
    CRYPTO: '加密货币',
    COMMODITY: '商品',
    GEOPOLITICS: '地缘政治',
    WAR: '战争',
    CRASH: '市场崩盘',
    EMERGENCY: '突发事件',
  },
  'en-US': {
    settings: 'Settings',
    language: 'Language',
    system_language: 'System Language',
    theme: 'Theme',
    dark_mode: 'Dark',
    light_mode: 'Light',
    english: 'English',
    chinese: '简体中文',
    logout: 'Logout',
    // News Tags
    FED: 'FED',
    ECB: 'ECB',
    BOJ: 'BOJ',
    INFLATION: 'Inflation',
    ECONOMY: 'Economy',
    CRYPTO: 'Crypto',
    COMMODITY: 'Commodity',
    GEOPOLITICS: 'Geopolitics',
    WAR: 'War',
    CRASH: 'Market Crash',
    EMERGENCY: 'Emergency',
  }
} as const

export type Locale = keyof typeof dictionaries
export type DictionaryKey = keyof typeof dictionaries['zh-CN']

interface I18nContextType {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: DictionaryKey) => string
}

const I18nContext = createContext<I18nContextType | undefined>(undefined)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>('zh-CN')

  useEffect(() => {
    const savedLocale = localStorage.getItem('app_locale') as Locale
    if (savedLocale && dictionaries[savedLocale]) {
      setLocaleState(savedLocale)
    }
  }, [])

  const setLocale = (newLocale: Locale) => {
    setLocaleState(newLocale)
    localStorage.setItem('app_locale', newLocale)
  }

  const t = (key: DictionaryKey): string => {
    const dict = dictionaries[locale] || dictionaries['zh-CN']
    return dict[key as keyof typeof dict] || key
  }

  return <I18nContext.Provider value={{ locale, setLocale, t }}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n 必须在 I18nProvider 内部使用')
  return context
}