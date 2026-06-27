import React, { useState, useRef, useEffect } from 'react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { Pencil, Loader2 } from 'lucide-react'

export interface InlineEditProps {
  value: string | number
  onSave: (val: string) => Promise<void> | void
  placeholder?: string
  className?: string
  inputClassName?: string
  type?: 'text' | 'number'
  validate?: (val: string | number) => string | null | undefined // 💡 新增：自定义校验函数
  suffix?: React.ReactNode // 可选的后缀，如 "%" 或 "$"
}

export function InlineEdit({ 
  value, 
  onSave, 
  placeholder = '-', 
  className, 
  inputClassName, 
  type = 'text',
  validate,
  suffix 
}: InlineEditProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [currentValue, setCurrentValue] = useState(value)
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const isSavingRef = useRef(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // 当外部 value 变化时同步内部状态
  useEffect(() => {
    setCurrentValue(value)
  }, [value])

  // 进入编辑状态时自动聚焦并将光标移至末尾
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      try {
        const len = inputRef.current.value.length
        inputRef.current.setSelectionRange(len, len)
      } catch (e) {
        // type="number" 在部分浏览器下不支持 setSelectionRange，利用 focus() 兜底即可
      }
    }
  }, [isEditing])

  const handleSave = async (fromBlur = false) => {
    if (isSavingRef.current) return

    // 1. 执行校验逻辑
    if (validate) {
      const errMsg = validate(currentValue)
      if (errMsg) {
        if (fromBlur) {
          // 💡 防焦点陷阱：如果用户点击了外部区域且输入非法，直接撤销更改并退出
          setCurrentValue(value)
          setIsEditing(false)
          setError(null)
          return
        }
        setError(errMsg)
        inputRef.current?.focus()
        return
      }
    }

    // 2. 校验通过，执行保存
    // 只有当值真正发生改变时才触发保存回调
    if (String(currentValue) !== String(value)) {
      setIsSaving(true)
      isSavingRef.current = true
      try {
        await onSave(String(currentValue))
        setIsEditing(false)
        setError(null)
      } catch (err: any) {
        setError(err.message || '保存失败')
        inputRef.current?.focus()
      } finally {
        setIsSaving(false)
        isSavingRef.current = false
      }
    } else {
      setIsEditing(false)
      setError(null)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (isSavingRef.current) return
    if (e.key === 'Enter') handleSave(false)
    if (e.key === 'Escape') {
      setCurrentValue(value) // 撤销更改，恢复原值
      setIsEditing(false)
      setError(null)
    }
  }

  if (isEditing) {
    return (
      <div className="relative inline-block w-full min-w-[60px]">
        {/* 💡 移动端防缩放：iOS Safari 强制要求输入框字体 >=16px，使用 text-[16px] 并在 PC 端保持 text-xs */}
        <Input
          ref={inputRef}
          type={type}
          value={currentValue}
          readOnly={isSaving}
          onChange={(e) => { setCurrentValue(e.target.value); if (error) setError(null); }}
          onBlur={() => handleSave(true)}
          onKeyDown={handleKeyDown}
          className={cn("h-6 px-1.5 py-0.5 text-[16px] md:text-xs rounded-sm w-full", error && "border-destructive focus-visible:ring-destructive/50", isSaving && "pr-6 opacity-70 pointer-events-none", inputClassName)}
        />
        {isSaving && (
          <div className="absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center justify-center z-10">
            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
          </div>
        )}
        {error && !isSaving && (
          <div className="absolute left-0 top-full mt-1 text-[10px] text-destructive bg-card border border-destructive/30 px-1.5 py-0.5 rounded shadow-sm z-50 whitespace-nowrap animate-in fade-in slide-in-from-top-1 pointer-events-none">
            {error}
          </div>
        )}
      </div>
    )
  }

  return (
    <span
      onDoubleClick={(e) => { e.stopPropagation(); setIsEditing(true) }}
      className={cn("group relative cursor-text px-1.5 py-0.5 rounded-sm border border-transparent hover:border-primary/30 hover:bg-primary/5 transition-colors inline-flex items-center gap-1 min-w-[30px]", className)}
      title="双击或点击图标编辑"
    >
      {value !== '' && value !== null && value !== undefined ? value : <span className="text-muted-foreground opacity-50">{placeholder}</span>}
      {suffix && <span>{suffix}</span>}
      
      {/* 💡 移动端交互：单独包装一层 span 增加防抖热区(Padding)，并在手机端默认半透明可见 */}
      <span 
        onClick={(e) => { e.stopPropagation(); setIsEditing(true) }}
        className="cursor-pointer p-1.5 -mx-1 -my-1 rounded-sm hover:bg-foreground/5 active:bg-foreground/10"
      >
        <Pencil className="h-2.5 w-2.5 opacity-40 md:opacity-0 md:group-hover:opacity-40 transition-opacity" />
      </span>
    </span>
  )
}