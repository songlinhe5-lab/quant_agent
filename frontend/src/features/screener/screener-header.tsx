'use client'

import React, { useState, useEffect, useRef } from 'react'
import { Database, Settings2, Save, FolderOpen, Share2, Pencil, Trash2, X, Copy, Check } from 'lucide-react'
import { useScreenerContext } from './screener-context'
import { useTradingModeStore } from '@/stores/useTradingModeStore'
import { useToast } from '@/hooks/use-toast'

/** 页头环境胶囊：SANDBOX 琥珀 / LIVE 转红，订阅策略仅入纸面，切 LIVE 必经全局 REAL_TRADE_EXECUTE 闸门 */
function ModeCapsule() {
  const mode = useTradingModeStore((s) => s.mode)
  const isLive = mode === 'LIVE'
  return (
    <span
      className={
        isLive
          ? 'text-[10px] font-mono font-bold text-red-500 bg-red-500/10 border border-red-500/40 rounded-full px-2 py-0.5'
          : 'text-[10px] font-mono font-bold text-amber-500 bg-amber-500/10 border border-amber-500/40 rounded-full px-2 py-0.5'
      }
      title={isLive ? 'LIVE 实盘模式：切换需通过 REAL_TRADE_EXECUTE 校验' : 'SANDBOX · 单次推演，无持久账本；订阅策略仅入纸面'}
    >
      {isLive ? 'LIVE · 实盘' : 'SANDBOX · 单次推演'}
    </span>
  )
}

export function ScreenerHeader() {
  const {
    setShowRagDict, setShowSubManager,
    savedScreens, loadSavedScreens, saveCurrentScreen, deleteSavedScreen, renameSavedScreen, applySavedScreen, shareCurrentScreen, nlpQuery,
  } = useScreenerContext()
  const { toast } = useToast()
  const [showScreens, setShowScreens] = useState(false)
  const [showSave, setShowSave] = useState(false)
  const [showShare, setShowShare] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveDesc, setSaveDesc] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingName, setEditingName] = useState('')
  const [editingDesc, setEditingDesc] = useState('')
  const [shareUrl, setShareUrl] = useState('')
  const [copied, setCopied] = useState(false)
  const screensRef = useRef<HTMLDivElement>(null)

  useEffect(() => { loadSavedScreens() }, [loadSavedScreens])

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (screensRef.current && !screensRef.current.contains(e.target as Node)) setShowScreens(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const openSave = () => {
    setSaveName(nlpQuery.slice(0, 20) || '')
    setSaveDesc('')
    setShowSave(true)
  }

  const handleSave = async () => {
    if (!saveName.trim()) { toast({ variant: 'destructive', title: '请填写名称' }); return }
    const res = await saveCurrentScreen({ name: saveName.trim(), description: saveDesc.trim() || undefined })
    if (res?.status === 'success') setShowSave(false)
  }

  const handleApply = async (s: any) => {
    setShowScreens(false)
    await applySavedScreen(s)
  }

  const handleShare = () => {
    const url = shareCurrentScreen()
    if (url) { setShareUrl(url); setCopied(false); setShowShare(true) }
  }

  const copyShare = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
      toast({ title: '已复制分享链接' })
      setTimeout(() => setCopied(false), 2000)
    } catch { /* 剪贴板不可用时忽略，用户可手动复制 */ }
  }

  const openRename = (s: any) => { setEditingId(s.id); setEditingName(s.name); setEditingDesc(s.description || '') }

  const submitRename = async () => {
    if (editingId == null || !editingName.trim()) return
    await renameSavedScreen(editingId, editingName.trim(), editingDesc.trim() || undefined)
    setEditingId(null)
  }

  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-1.5 rounded-full bg-violet-500 dark:bg-violet-400 transition-colors duration-300" aria-hidden="true" />
      <h1 className="text-base font-bold tracking-tight">智能量化选股</h1>
      <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">Agentic Screener</span>
      {/* UIRF: 页头环境胶囊 —— 沙箱推演口径显性化（全局横幅之外的页面级提示） */}
      <ModeCapsule />
      <div className="ml-auto flex items-center gap-2">
        <button onClick={openSave} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors bg-secondary/30 hover:bg-secondary/60 px-3 py-1.5 rounded-lg border border-border/50 shadow-sm">
          <Save className="h-3.5 w-3.5" />保存条件</button>
        <div className="relative" ref={screensRef}>
          <button onClick={() => { setShowScreens(v => !v); if (!showScreens) loadSavedScreens() }} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors bg-secondary/30 hover:bg-secondary/60 px-3 py-1.5 rounded-lg border border-border/50 shadow-sm">
            <FolderOpen className="h-3.5 w-3.5" />我的筛选{savedScreens.length > 0 && <span className="ml-0.5 rounded-full bg-violet-500/20 text-violet-500 dark:text-violet-400 px-1.5 text-[10px]">{savedScreens.length}</span>}</button>
          {showScreens && (
            <div className="absolute right-0 top-full mt-1 w-72 bg-card border border-border/50 rounded-lg shadow-xl z-50 overflow-hidden animate-in fade-in slide-in-from-top-2 max-h-[60vh] flex flex-col">
              <div className="px-3 py-2 border-b border-border/30 bg-secondary/20 flex justify-between items-center">
                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">我的筛选条件</span>
                <button onClick={openSave} className="text-[10px] text-violet-500 hover:underline">＋ 新建</button>
              </div>
              <div className="overflow-y-auto custom-scrollbar flex-1">
                {savedScreens.length === 0 ? (
                  <div className="text-center text-[11px] text-muted-foreground py-6 leading-relaxed">暂无保存的条件<br />点击「保存条件」收藏当前筛选</div>
                ) : (
                  savedScreens.map((s: any) => (
                    <div key={s.id} className="px-3 py-2 border-b border-border/20 hover:bg-secondary/40 transition-colors">
                      {editingId === s.id ? (
                        <div className="space-y-1.5">
                          <input value={editingName} onChange={e => setEditingName(e.target.value)} className="w-full bg-secondary/60 border border-border/40 rounded px-2 py-1 text-[11px] text-foreground outline-none focus:border-violet-500" placeholder="名称" />
                          <input value={editingDesc} onChange={e => setEditingDesc(e.target.value)} className="w-full bg-secondary/60 border border-border/40 rounded px-2 py-1 text-[11px] text-foreground outline-none focus:border-violet-500" placeholder="描述（可选）" />
                          <div className="flex gap-1.5">
                            <button onClick={submitRename} className="flex-1 bg-violet-500/20 text-violet-500 dark:text-violet-400 rounded px-2 py-1 text-[10px] hover:bg-violet-500/30">保存</button>
                            <button onClick={() => setEditingId(null)} className="flex-1 bg-secondary/60 rounded px-2 py-1 text-[10px] hover:bg-secondary/80">取消</button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <button onClick={() => handleApply(s)} className="text-left w-full block">
                            <div className="text-[12px] font-medium text-foreground truncate">{s.name}</div>
                            {s.description && <div className="text-[10px] text-muted-foreground truncate">{s.description}</div>}
                          </button>
                          <div className="flex items-center gap-1.5 mt-1">
                            <button onClick={() => handleApply(s)} className="flex-1 bg-secondary/60 hover:bg-secondary/80 rounded px-2 py-0.5 text-[10px] text-muted-foreground">应用</button>
                            <button onClick={() => openRename(s)} className="p-1 rounded hover:bg-secondary/80 text-muted-foreground" title="重命名"><Pencil className="h-3 w-3" /></button>
                            <button onClick={() => deleteSavedScreen(s.id)} className="p-1 rounded hover:bg-red-500/10 text-red-500" title="删除"><Trash2 className="h-3 w-3" /></button>
                          </div>
                        </>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
        <button onClick={handleShare} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors bg-secondary/30 hover:bg-secondary/60 px-3 py-1.5 rounded-lg border border-border/50 shadow-sm">
          <Share2 className="h-3.5 w-3.5" />分享</button>
        <button onClick={() => setShowRagDict(true)} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors bg-secondary/30 hover:bg-secondary/60 px-3 py-1.5 rounded-lg border border-border/50 shadow-sm">
          <Database className="h-3.5 w-3.5" />RAG 词库</button>
        <button onClick={() => setShowSubManager(true)} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors bg-secondary/30 hover:bg-secondary/60 px-3 py-1.5 rounded-lg border border-border/50 shadow-sm">
          <Settings2 className="h-3.5 w-3.5" />管理订阅</button>
      </div>

      {/* 保存条件弹窗 */}
      {showSave && (
        <div className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setShowSave(false)}>
          <div className="w-full max-w-md bg-card border border-border/40 rounded-xl overflow-hidden shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/30 bg-secondary/20">
              <h3 className="text-sm font-bold flex items-center gap-2"><Save className="h-4 w-4 text-violet-500" />保存筛选条件</h3>
              <button onClick={() => setShowSave(false)} className="p-1 rounded-md hover:bg-secondary/50 text-muted-foreground"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-4 space-y-3">
              <div className="space-y-1">
                <label className="text-[11px] text-muted-foreground">名称 *</label>
                <input value={saveName} onChange={e => setSaveName(e.target.value)} className="w-full bg-secondary/60 border border-border/40 rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:border-violet-500" placeholder="例如：低估值高股息龙头" />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-muted-foreground">描述（可选）</label>
                <textarea value={saveDesc} onChange={e => setSaveDesc(e.target.value)} rows={3} className="w-full bg-secondary/60 border border-border/40 rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:border-violet-500 resize-none" placeholder="备注该筛选条件的用途..." />
              </div>
              <div className="text-[10px] text-muted-foreground bg-secondary/30 rounded-lg px-3 py-2 border border-border/30">将保存当前的 DSL 筛选条件{nlpQuery ? `（来自：${nlpQuery.slice(0, 30)}）` : ''}</div>
              <div className="flex justify-end gap-2 pt-1">
                <button onClick={() => setShowSave(false)} className="px-3 py-1.5 rounded-lg text-xs bg-secondary/60 hover:bg-secondary/80">取消</button>
                <button onClick={handleSave} className="px-3 py-1.5 rounded-lg text-xs bg-violet-500 text-white hover:bg-violet-600">保存</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 分享弹窗 */}
      {showShare && (
        <div className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setShowShare(false)}>
          <div className="w-full max-w-md bg-card border border-border/40 rounded-xl overflow-hidden shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/30 bg-secondary/20">
              <h3 className="text-sm font-bold flex items-center gap-2"><Share2 className="h-4 w-4 text-violet-500" />分享筛选条件</h3>
              <button onClick={() => setShowShare(false)} className="p-1 rounded-md hover:bg-secondary/50 text-muted-foreground"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-4 space-y-3">
              <p className="text-[11px] text-muted-foreground leading-relaxed">复制以下链接发送给他人，对方打开后将自动填充该筛选条件。</p>
              <div className="flex items-center gap-2">
                <input readOnly value={shareUrl} className="flex-1 bg-secondary/60 border border-border/40 rounded-lg px-3 py-2 text-[11px] text-foreground font-mono outline-none" />
                <button onClick={copyShare} className="flex items-center gap-1 px-3 py-2 rounded-lg text-xs bg-violet-500 text-white hover:bg-violet-600 whitespace-nowrap">{copied ? <><Check className="h-3.5 w-3.5" />已复制</> : <><Copy className="h-3.5 w-3.5" />复制</>}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
