import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { AppRoutes } from './App'
import { DataProvider } from './api/DataContext'
import './styles/tokens.css'
import './components/ui.css'
import './components/layout.css'
import './pages/pages.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <DataProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </DataProvider>
  </StrictMode>,
)
