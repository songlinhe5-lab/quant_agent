/// <reference types="vite/client" />

// §14.1 生产环境零 Mock 数据：仅 DEV + 显式开启 VITE_ENABLE_MOCK 时才注入 mock。
// PROD 构建下该值为 undefined，MOCK_ENABLED 恒为 false。
interface ImportMetaEnv {
  readonly VITE_ENABLE_MOCK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
