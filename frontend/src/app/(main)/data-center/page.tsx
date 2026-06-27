'use client';

import { DataCenterModule } from '@/features/trading/data-center';

export default function DataCenterPage() {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
      <DataCenterModule />
    </div>
  );
}