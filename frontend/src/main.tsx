import React from 'react'
import ReactDOM from 'react-dom/client'
import { ThemeProvider } from './components/layout/theme-provider'
import { AuthProvider } from './contexts/auth-context'
import { I18nProvider } from './contexts/i18n'
import App from './App'
import './styles/globals.css'

ReactDOM.createRoot(document.getElementById('app')!).render(
  <React.StrictMode>
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
      <I18nProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </I18nProvider>
    </ThemeProvider>
  </React.StrictMode>
)
