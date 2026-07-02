import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ThemeProvider } from './components/layout/theme-provider'
import { AuthProvider } from './contexts/auth-context'
import { I18nProvider } from './contexts/i18n'
import App from './App'
import './styles/globals.css'

// Quant Agent Frontend Entry Point

ReactDOM.createRoot(document.getElementById('app')!).render(
  <React.StrictMode>
    <BrowserRouter>
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
      <I18nProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </I18nProvider>
    </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>
)
