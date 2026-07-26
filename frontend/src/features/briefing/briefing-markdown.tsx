'use client'

/**
 * BRD-01: 早报 Markdown 渲染器
 * 不依赖 @tailwindcss/typography 插件，直接用 Tailwind arbitrary variant 覆写
 * 标题/表格/引用/列表样式，保证暗色主题下清晰可读。
 */
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function BriefingMarkdown({ content }: { content: string }) {
  return (
    <div className="text-sm leading-relaxed text-slate-700 dark:text-slate-200
      [&_h1]:text-xl [&_h1]:font-black [&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:text-transparent [&_h1]:bg-clip-text [&_h1]:bg-gradient-to-r [&_h1]:from-blue-500 [&_h1]:to-purple-500
      [&_h2]:text-lg [&_h2]:font-bold [&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:pb-1 [&_h2]:text-slate-900 dark:[&_h2]:text-slate-100 [&_h2]:border-b [&_h2]:border-slate-200 dark:[&_h2]:border-slate-800
      [&_h3]:text-base [&_h3]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1 [&_h3]:text-slate-800 dark:[&_h3]:text-slate-200
      [&_p]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:my-2
      [&_li]:my-1 [&_strong]:font-bold [&_strong]:text-slate-900 dark:[&_strong]:text-white
      [&_a]:text-blue-500 [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:border-amber-400 [&_blockquote]:pl-3 [&_blockquote]:text-amber-700 dark:[&_blockquote]:text-amber-300 [&_blockquote]:italic [&_blockquote]:my-2
      [&_table]:w-full [&_table]:text-xs [&_table]:my-3 [&_table]:border-collapse
      [&_th]:border [&_th]:border-slate-300 dark:[&_th]:border-slate-700 [&_th]:px-2 [&_th]:py-1 [&_th]:bg-slate-100 dark:[&_th]:bg-slate-800 [&_th]:text-left [&_th]:font-semibold
      [&_td]:border [&_td]:border-slate-300 dark:[&_td]:border-slate-700 [&_td]:px-2 [&_td]:py-1
      [&_code]:bg-slate-100 dark:[&_code]:bg-slate-800 [&_code]:px-1 [&_code]:rounded [&_code]:text-xs">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  )
}
