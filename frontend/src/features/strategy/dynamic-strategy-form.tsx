import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Settings2, Play, Code2, Sparkles, Bot, ChevronDown, Check, HelpCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

interface ParamSchema {
  name: string;
  type: string;
  default: any;
  required: boolean;
  description?: string;
  options?: any[];
  min?: number;  // 💡 扩展支持滑块最小值
  max?: number;  // 💡 扩展支持滑块最大值
  step?: number; // 💡 扩展支持滑块步长
}

interface StrategySchema {
  class_name: string;
  parameters: ParamSchema[];
}

function SearchableSelect({ options, value, onChange }: { options: any[], value: any, onChange: (val: any) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrapperRef = React.useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const filtered = options.filter(opt => String(opt).toLowerCase().includes(query.toLowerCase()));

  return (
    <div ref={wrapperRef} className="relative w-full">
      <button
        type="button"
        onClick={() => { setOpen(!open); setQuery(''); }}
        className="flex h-8 w-full items-center justify-between rounded-md border border-border/50 bg-background px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary transition-colors hover:border-border"
      >
        <span className="truncate">{value !== '' && value !== undefined ? String(value) : '请选择...'}</span>
        <ChevronDown className={cn("h-3 w-3 opacity-50 transition-transform duration-200", open && "rotate-180")} />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-border/40 bg-card text-card-foreground shadow-2xl p-1 custom-scrollbar animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="sticky top-0 bg-card pb-1 z-10 pt-1 px-1">
            <Input
              autoFocus
              placeholder="搜索选项..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="h-7 text-xs border-border/50 focus-visible:ring-1 focus-visible:ring-primary/50 bg-background/50 backdrop-blur-sm"
              onClick={e => e.stopPropagation()}
            />
          </div>
          <div className="pt-1">
            {filtered.length === 0 ? (
              <div className="py-3 text-center text-[10px] text-muted-foreground">无匹配结果</div>
            ) : (
              filtered.map(opt => (
                <div
                  key={String(opt)}
                  onClick={() => { onChange(opt); setOpen(false); }}
                  className={cn(
                    "cursor-pointer rounded-sm px-2 py-1.5 text-xs hover:bg-secondary flex items-center justify-between transition-colors",
                    value === opt ? "bg-primary/10 text-primary font-bold" : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  <span className="truncate">{String(opt)}</span>
                  {value === opt && <Check className="h-3 w-3 flex-shrink-0" />}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

interface DynamicStrategyFormProps {
  schema: StrategySchema[];
  onSubmit: (className: string, data: Record<string, any>, isSilent?: boolean) => void;
  onOptimize?: (className: string, data: Record<string, any>) => void;
  onDeploy?: (className: string, data: Record<string, any>) => void;
  className?: string;
}

export function DynamicStrategyForm({ schema, onSubmit, onOptimize, onDeploy, className }: DynamicStrategyFormProps) {
  // 存储所有类的表单数据，外层键为类名，内层为参数键值对
  const [formData, setFormData] = useState<Record<string, Record<string, any>>>({});

  // 当 schema 更新时，自动提取默认值初始化表单
  useEffect(() => {
    const initialData: Record<string, Record<string, any>> = {};
    schema.forEach(strat => {
      initialData[strat.class_name] = {};
      strat.parameters.forEach(param => {
        initialData[strat.class_name][param.name] = param.default !== null ? param.default : (param.type === 'bool' ? false : '');
      });
    });
    setFormData(initialData);
  }, [schema]);

  // 处理输入变化，并进行数据类型转换防卫
  const handleChange = (className: string, name: string, value: any, type: string) => {
    let parsedValue = value;
    if (type === 'int' || type === 'float') {
      // 💡 容许输入以 ":" 或 "," 分隔的字符串用于网格寻优
      if (typeof value === 'string' && (value.includes(':') || value.includes(','))) {
        parsedValue = value; 
      } else {
        parsedValue = type === 'int' ? parseInt(value, 10) : parseFloat(value);
        if (isNaN(parsedValue)) parsedValue = value; // 若解析失败保留字符串，让用户能继续打字
      }
    }

    setFormData(prev => ({
      ...prev,
      [className]: {
        ...prev[className],
        [name]: parsedValue
      }
    }));
  };

  if (!schema || schema.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-6 border border-dashed border-border/50 rounded-xl bg-secondary/10 text-muted-foreground text-xs">
        <Code2 className="h-6 w-6 mb-2 opacity-50" />
        未检测到可配置的策略参数
      </div>
    );
  }

  return (
    <div className={cn("space-y-4", className)}>
      {schema.map((strat) => (
        <Card key={strat.class_name} className="bg-slate-50/50 dark:bg-black/20 border-border/40 shadow-sm overflow-hidden transition-colors hover:border-primary/30">
          <CardHeader className="py-3 px-4 bg-secondary/30 border-b border-border/20">
            <CardTitle className="text-xs font-bold font-mono text-primary flex items-center gap-2 tracking-tight">
              <Settings2 className="w-3.5 h-3.5" />
              {strat.class_name} <span className="text-muted-foreground font-normal">参数面板</span>
            </CardTitle>
          </CardHeader>
          
          <CardContent className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 pt-4 pb-5 px-4">
            {strat.parameters.map(param => (
              <div key={param.name} className="flex flex-col gap-2">
                <Label htmlFor={`${strat.class_name}-${param.name}`} className="text-[10px] text-muted-foreground font-mono flex flex-col gap-1 uppercase tracking-wider">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1.5">
                      {param.name} {param.required && <span className="text-red-500">*</span>}
                      {(param.type === 'int' || param.type === 'float') && (
                        <TooltipProvider delayDuration={0}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <HelpCircle className="h-3 w-3 text-muted-foreground/50 hover:text-primary cursor-help" />
                            </TooltipTrigger>
                            <TooltipContent side="right" className="max-w-[220px] text-xs font-sans">
                              <p className="font-bold mb-1">网格寻优支持以下高级语法：</p>
                              <ul className="list-disc pl-3 text-muted-foreground space-y-1">
                                <li><span className="text-primary">范围:</span> <code className="bg-secondary px-1 rounded">10:50:5</code> (起:止:步长)</li>
                                <li><span className="text-primary">集合:</span> <code className="bg-secondary px-1 rounded">10,20,30</code> (离散值)</li>
                              </ul>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      )}
                    </span>
                  </div>
                  {/* 💡 显示从 Python 提取出的中文 Docstring 参数说明 */}
                  {param.description && (
                    <span className="text-[9px] text-muted-foreground/60 normal-case font-sans leading-tight">{param.description}</span>
                  )}
                </Label>

                {param.options && Array.isArray(param.options) ? (
                  <SearchableSelect 
                    options={param.options} 
                    value={formData[strat.class_name]?.[param.name] ?? ''} 
                    onChange={(val) => handleChange(strat.class_name, param.name, val, param.type)} 
                  />
                ) : param.type === 'bool' ? (
                  <div className="h-8 flex items-center">
                    <Switch id={`${strat.class_name}-${param.name}`} checked={!!formData[strat.class_name]?.[param.name]} onCheckedChange={(checked) => handleChange(strat.class_name, param.name, checked, param.type)} />
                  </div>
                ) : param.type === 'int' || param.type === 'float' ? (
                  <div className="flex flex-col gap-1 relative group">
                    <Input id={`${strat.class_name}-${param.name}`} type="text" placeholder={param.type === 'int' ? "单值或范围(10:50:5)" : "单值或范围"} value={formData[strat.class_name]?.[param.name] ?? ''} onChange={(e) => handleChange(strat.class_name, param.name, e.target.value, param.type)} className="h-8 text-xs font-mono bg-background border-border/50 focus-visible:ring-1 placeholder:text-muted-foreground/30" />
                    {/* 💡 智能滑块：仅在单值模式下显现，自动推算合理的物理拖拽边界 */}
                    {(() => {
                      const val = formData[strat.class_name]?.[param.name];
                      const isSingleNum = typeof val === 'number' || (typeof val === 'string' && !val.includes(':') && !val.includes(','));
                      if (!isSingleNum || val === '') return null;
                      
                      const numVal = Number(val) || 0;
                      const min = param.min ?? (numVal > 0 ? 0 : (numVal < 0 ? numVal * 2 : 0));
                      const max = param.max ?? (numVal > 0 ? Math.max(10, numVal * 2.5) : 100);
                      const step = param.step ?? (param.type === 'int' ? 1 : 0.01);
                      
                      return (
                        <div className="px-1 opacity-30 group-hover:opacity-100 transition-opacity duration-300">
                          <input 
                            type="range" min={min} max={max} step={step} value={numVal} 
                            onChange={(e) => handleChange(strat.class_name, param.name, e.target.value, param.type)} 
                            onPointerUp={() => onSubmit(strat.class_name, formData[strat.class_name], true)}
                            className="w-full h-1 bg-border/50 rounded-lg appearance-none cursor-ew-resize accent-primary focus:outline-none block" 
                            title={`拖动快速调整: ${numVal}`}
                          />
                        </div>
                      );
                    })()}
                  </div>
                ) : (
                  <Input id={`${strat.class_name}-${param.name}`} type="text" value={formData[strat.class_name]?.[param.name] ?? ''} onChange={(e) => handleChange(strat.class_name, param.name, e.target.value, param.type)} className="h-8 text-xs bg-background border-border/50 focus-visible:ring-1" />
                )}
              </div>
            ))}
          </CardContent>
          
          <CardFooter className="pt-0 pb-3 px-4 flex justify-between items-center">
             {onOptimize ? (
               <Button size="sm" variant="outline" onClick={() => onOptimize(strat.class_name, formData[strat.class_name])} className="h-7 px-3 text-[10px] text-indigo-500 border-indigo-500/30 hover:bg-indigo-500/10 font-bold tracking-widest uppercase gap-1">
                 <Sparkles className="w-3 h-3" fill="currentColor" /> 智能寻优
               </Button>
             ) : <div />}
             
             <div className="flex gap-2">
               {onDeploy && (
                 <Button size="sm" onClick={() => onDeploy(strat.class_name, formData[strat.class_name])} className="h-7 px-3 text-[10px] bg-amber-500/10 text-amber-600 dark:text-amber-500 hover:bg-amber-500/20 border border-amber-500/30 transition-all font-bold tracking-widest uppercase">
                   <Bot className="w-3 h-3 mr-1" /> 部署实盘
                 </Button>
               )}
               <Button size="sm" onClick={() => onSubmit(strat.class_name, formData[strat.class_name])} className="h-7 px-3 text-[10px] bg-primary/10 text-primary hover:bg-primary/20 hover:shadow-[0_0_10px_rgba(var(--primary),0.2)] transition-all font-bold tracking-widest uppercase">
                 <Play className="w-3 h-3 mr-1" fill="currentColor" /> 应用推演
               </Button>
             </div>
          </CardFooter>
        </Card>
      ))}
    </div>
  );
}
