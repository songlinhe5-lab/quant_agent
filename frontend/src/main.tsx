import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ThemeProvider } from './components/layout/theme-provider'
import { AuthProvider } from './contexts/auth-context'
import { I18nProvider } from './contexts/i18n'
import App from './App'
import { initWebVitals } from './lib/web-vitals-reporter'
import { ModuleErrorBoundary } from './components/error-boundary'
import './styles/globals.css'

// Quant Agent Frontend Entry Point
initWebVitals()

/** FE-14: Lighthouse / 无障碍测量时关闭动效 */
function applyReduceMotionBaseline() {
  const params = new URLSearchParams(window.location.search)
  const force =
    params.get('lighthouse') === '1' ||
    params.get('reduceMotion') === '1' ||
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (force) document.documentElement.classList.add('reduce-motion')
}
applyReduceMotionBaseline()

ReactDOM.createRoot(document.getElementById('app')!).render(
  <React.StrictMode>
    <ModuleErrorBoundary name="AppRoot">
      <BrowserRouter>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
          <I18nProvider>
            <AuthProvider>
              <App />
            </AuthProvider>
          </I18nProvider>
        </ThemeProvider>
      </BrowserRouter>
    </ModuleErrorBoundary>
  </React.StrictMode>
)
