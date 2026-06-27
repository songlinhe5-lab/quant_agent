'use client';

import { QuotesModule } from '@/features/trading/quotes';

export default function MarketPage() {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
      <QuotesModule />
    </div>
  );
}