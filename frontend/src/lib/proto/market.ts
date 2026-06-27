// ES Module 包装文件，将 CommonJS 的 market.js 正确导出
import marketJs from './market.js'

// market.js 导出的是 $root 对象，其中包含 market 命名空间
const $root = marketJs.default || marketJs

export const market = $root.market
export default $root
