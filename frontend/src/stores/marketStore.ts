import { create } from 'zustand';
import { persist, devtools } from 'zustand/middleware';

export interface MarketState {
  // --- 状态 (State) ---
  currentTicker: string;
  currentTickerName: string;
  currentTickerType: string;

  // --- 动作 (Actions) ---
  /** 设置当前聚焦的全局标的 */
  setCurrentTicker: (symbol: string, name?: string, type?: string) => void;
  /** 重置为默认标的 */
  resetTicker: () => void;
}

export const useMarketStore = create<MarketState>()(
  devtools(
    persist(
      (set) => ({
        // 默认状态：以腾讯控股作为默认展示标的
        currentTicker: '0700.HK',
        currentTickerName: '腾讯控股',
        currentTickerType: 'EQUITY',
  
        setCurrentTicker: (symbol, name = '', type = 'EQUITY') =>
          set({
            currentTicker: symbol,
            currentTickerName: name,
            currentTickerType: type,
          }),
  
        resetTicker: () => set({ currentTicker: '0700.HK', currentTickerName: '腾讯控股', currentTickerType: 'EQUITY' }),
      }),
      {
        name: 'quant-market-storage', // LocalStorage 中保存的 Key
      }
    )
  )
);