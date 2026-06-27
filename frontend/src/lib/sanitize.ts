/**
 * SEC-08: XSS 过滤工具
 * 所有通过 dangerouslySetInnerHTML 渲染的 HTML 内容必须经过 DOMPurify 净化。
 * 严禁在项目中直接使用 dangerouslySetInnerHTML 而不经过此工具过滤。
 */
import DOMPurify, { type Config as PurifyConfig } from 'dompurify'

// 预配置 DOMPurify 安全策略：
// - ALLOW_TAGS: 白名单 HTML 标签（覆盖 Mermaid SVG 渲染所需的标签）
// - ALLOW_ATTR: 白名单属性（覆盖 SVG/样式所需属性）
// - FORBID_TAGS: 绝对禁止的标签（脚本、表单等危险元素）
// - FORBID_ATTR: 绝对禁止的属性（事件处理器等）
const PURIFY_CONFIG: PurifyConfig = {
  ALLOW_TAGS: [
    // 标准文本标签
    'div', 'span', 'p', 'a', 'b', 'i', 'u', 'em', 'strong', 'sub', 'sup',
    'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    // 列表
    'ul', 'ol', 'li',
    // 表格
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    // SVG（Mermaid 图表渲染必需）
    'svg', 'g', 'path', 'rect', 'circle', 'line', 'polyline', 'polygon',
    'text', 'tspan', 'defs', 'marker', 'foreignObject', 'use', 'image',
    // 代码块
    'code', 'pre', 'blockquote',
  ],
  ALLOW_ATTR: [
    // 通用属性
    'class', 'id', 'style', 'title', 'role', 'tabindex', 'dir', 'lang',
    // SVG 属性
    'd', 'fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-linecap',
    'stroke-linejoin', 'transform', 'viewBox', 'xmlns', 'width', 'height',
    'x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry',
    'dx', 'dy', 'text-anchor', 'dominant-baseline', 'alignment-baseline',
    'marker-end', 'marker-start', 'marker-mid', 'refX', 'refY',
    'markerWidth', 'markerHeight', 'orient', 'points',
    // 链接属性
    'href', 'target', 'rel',
    // 表格属性
    'colspan', 'rowspan',
    // data 属性（Mermaid 可能生成）
    'data-error-type',
  ],
  FORBID_TAGS: ['script', 'form', 'input', 'button', 'textarea', 'select', 'iframe', 'object', 'embed'],
  FORBID_ATTR: ['onerror', 'onclick', 'onload', 'onmouseover', 'onfocus', 'onblur'],
}

/**
 * 净化 HTML 字符串，防止 XSS 攻击
 * @param dirty - 未净信的原始 HTML 字符串
 * @returns 经过 DOMPurify 过滤的安全 HTML
 */
export function sanitizeHtml(dirty: string): string {
  return DOMPurify.sanitize(dirty, PURIFY_CONFIG) as string
}

/**
 * 严格模式净化：仅允许纯文本和基础格式标签，用于用户输入场景
 * @param dirty - 用户输入的原始文本
 * @returns 仅包含安全文本标签的 HTML
 */
export function sanitizeUserInput(dirty: string): string {
  return DOMPurify.sanitize(dirty, {
    ALLOWED_TAGS: ['b', 'i', 'em', 'strong', 'span', 'br'],
    ALLOWED_ATTR: [],
  }) as string
}
