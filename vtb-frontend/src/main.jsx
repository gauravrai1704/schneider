import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { LiveFeedProvider } from './api'
import { ThemeProvider } from './theme'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider>
      <LiveFeedProvider>
        <App />
      </LiveFeedProvider>
    </ThemeProvider>
  </React.StrictMode>,
)
