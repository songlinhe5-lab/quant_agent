"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Slider } from "@/components/ui/slider"

interface OrderPanelProps {
  currentPrice: number
  availableBalance: number
  symbol: string
  onSubmit?: (order: { side: "buy" | "sell"; type: "market" | "limit"; price: number; amount: number }) => void
}

export function OrderPanel({ currentPrice, availableBalance, symbol, onSubmit }: OrderPanelProps) {
  const [side, setSide] = useState<"buy" | "sell">("buy")
  const [orderType, setOrderType] = useState<"limit" | "market">("limit")
  const [price, setPrice] = useState(currentPrice.toString())
  const [amount, setAmount] = useState("")
  const [sliderValue, setSliderValue] = useState([0])

  const total = parseFloat(amount || "0") * parseFloat(price || "0")
  const isBuy = side === "buy"

  const handleSliderChange = (value: number[]) => {
    setSliderValue(value)
    const maxAmount = isBuy 
      ? availableBalance / parseFloat(price || "1")
      : availableBalance
    setAmount((maxAmount * value[0] / 100).toFixed(4))
  }

  const handleSubmit = () => {
    onSubmit?.({
      side,
      type: orderType,
      price: parseFloat(price),
      amount: parseFloat(amount),
    })
  }

  return (
    <div className="glass-card rounded-lg p-4">
      <h3 className="font-semibold mb-4">下单面板</h3>

      {/* Buy/Sell Toggle */}
      <div className="grid grid-cols-2 gap-1 p-1 bg-secondary/50 rounded-lg mb-4">
        <button
          onClick={() => setSide("buy")}
          className={cn(
            "py-2 rounded-md text-sm font-medium transition-all duration-200",
            side === "buy" 
              ? "bg-emerald-400 text-emerald-950" 
              : "text-muted-foreground hover:text-foreground"
          )}
          title="买入"
          aria-label="切换到买入模式"
        >
          买入
        </button>
        <button
          onClick={() => setSide("sell")}
          className={cn(
            "py-2 rounded-md text-sm font-medium transition-all duration-200",
            side === "sell" 
              ? "bg-red-400 text-red-950" 
              : "text-muted-foreground hover:text-foreground"
          )}
          title="卖出"
          aria-label="切换到卖出模式"
        >
          卖出
        </button>
      </div>

      {/* Order Type Toggle */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setOrderType("limit")}
          className={cn(
            "px-3 py-1.5 rounded text-xs font-medium transition-colors",
            orderType === "limit" 
              ? "bg-accent text-foreground" 
              : "text-muted-foreground hover:text-foreground"
          )}
          title="限价单"
          aria-label="切换到限价单模式"
        >
          限价
        </button>
        <button
          onClick={() => setOrderType("market")}
          className={cn(
            "px-3 py-1.5 rounded text-xs font-medium transition-colors",
            orderType === "market" 
              ? "bg-accent text-foreground" 
              : "text-muted-foreground hover:text-foreground"
          )}
          title="市价单"
          aria-label="切换到市价单模式"
        >
          市价
        </button>
      </div>

      {/* Price Input */}
      {orderType === "limit" && (
        <div className="mb-4">
          <label htmlFor="price-input" className="text-xs text-muted-foreground mb-1.5 block">
            价格 (USD)
          </label>
          <Input
            id="price-input"
            type="number"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="font-mono bg-input border-border"
            placeholder="0.00"
            aria-label="输入价格"
          />
        </div>
      )}

      {/* Amount Input */}
      <div className="mb-4">
        <label htmlFor="amount-input" className="text-xs text-muted-foreground mb-1.5 block">
          数量 ({symbol.split("/")[0]})
        </label>
        <Input
          id="amount-input"
          type="number"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="font-mono bg-input border-border"
          placeholder="0.0000"
          aria-label="输入数量"
        />
      </div>

      {/* Percentage Slider */}
      <div className="mb-4">
        <Slider
          value={sliderValue}
          onValueChange={handleSliderChange}
          max={100}
          step={25}
          className={cn(
            "py-2",
            isBuy ? "[&_[role=slider]]:bg-emerald-400" : "[&_[role=slider]]:bg-red-400"
          )}
          aria-label="调整下单比例"
        />
        <div className="flex justify-between text-xs text-muted-foreground mt-1">
          <span>0%</span>
          <span>25%</span>
          <span>50%</span>
          <span>75%</span>
          <span>100%</span>
        </div>
      </div>

      {/* Total */}
      <div className="flex justify-between items-center py-3 border-t border-border/50 mb-4">
        <span className="text-sm text-muted-foreground">总金额</span>
        <span className="font-mono font-medium">
          ${total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD
        </span>
      </div>

      {/* Available Balance */}
      <div className="flex justify-between items-center text-xs text-muted-foreground mb-4">
        <span>可用余额</span>
        <span className="font-mono">${availableBalance.toLocaleString()} USD</span>
      </div>

      {/* Submit Button */}
      <Button
        onClick={handleSubmit}
        disabled={!amount || parseFloat(amount) <= 0}
        className={cn(
          "w-full font-semibold transition-all duration-200",
          isBuy 
            ? "bg-emerald-400 hover:bg-emerald-500 text-emerald-950" 
            : "bg-red-400 hover:bg-red-500 text-red-950"
        )}
        title={isBuy ? `买入 ${symbol}` : `卖出 ${symbol}`}
        aria-label={isBuy ? `确认买入 ${symbol}` : `确认卖出 ${symbol}`}
      >
        {isBuy ? "买入" : "卖出"} {symbol.split("/")[0]}
      </Button>
    </div>
  )
}
