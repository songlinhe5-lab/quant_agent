/**
 * PT-02b: 纸面组合模块入口
 */
import { Routes, Route } from 'react-router-dom'
import { PaperListPage } from './page'
import { PortfolioDetail } from './detail/portfolio-detail'

export function PaperModule() {
  return (
    <Routes>
      <Route index element={<PaperListPage />} />
      <Route path=":portfolioId" element={<PortfolioDetail />} />
    </Routes>
  )
}

export default PaperModule
