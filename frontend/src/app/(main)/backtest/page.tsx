'use client';

import { BacktestModule } from '@/features/trading/backtest';

export default function BacktestPage() {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
      <BacktestModule />
    </div>
  );
}