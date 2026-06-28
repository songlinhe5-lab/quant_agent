/**
 * Vitest 测试 Setup
 * TEST-08: 测试框架与脚手架搭建
 */

import '@testing-library/jest-dom'

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})

// Mock IntersectionObserver
class MockIntersectionObserver {
  observe = () => {}
  unobserve = () => {}
  disconnect = () => {}
}

Object.defineProperty(window, 'IntersectionObserver', {
  writable: true,
  value: MockIntersectionObserver,
})

// Mock ResizeObserver
class MockResizeObserver {
  observe = () => {}
  unobserve = () => {}
  disconnect = () => {}
}

Object.defineProperty(window, 'ResizeObserver', {
  writable: true,
  value: MockResizeObserver,
})

// Mock indexedDB
const mockIndexedDB = {
  open: () => ({
    onsuccess: null,
    onerror: null,
    onupgradeneeded: null,
    result: {
      createObjectStore: () => ({
        createIndex: () => {},
        put: () => ({ onsuccess: null, onerror: null }),
        get: () => ({ onsuccess: null, onerror: null }),
        delete: () => ({ onsuccess: null, onerror: null }),
      }),
      objectStoreNames: { contains: () => false },
      transaction: () => ({
        objectStore: () => ({
          put: () => ({ onsuccess: null, onerror: null }),
          get: () => ({ onsuccess: null, onerror: null }),
          delete: () => ({ onsuccess: null, onerror: null }),
          count: () => ({ onsuccess: null, onerror: null }),
          openCursor: () => ({ onsuccess: null, onerror: null }),
          index: () => ({ openCursor: () => ({ onsuccess: null, onerror: null }), openKeyCursor: () => ({ onsuccess: null, onerror: null }) }),
          clear: () => ({ onsuccess: null, onerror: null }),
        }),
      }),
    },
  }),
}

Object.defineProperty(window, 'indexedDB', {
  writable: true,
  value: mockIndexedDB,
})

// Suppress console in tests (可选)
if (process.env.SUPPRESS_CONSOLE !== 'false') {
  // 保留 console.error 用于测试断言
  const originalWarn = console.warn
  console.warn = (...args: unknown[]) => {
    if (typeof args[0] === 'string' && args[0].includes('[MSW]')) return
    originalWarn(...args)
  }
}
