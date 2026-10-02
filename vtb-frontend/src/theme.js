import { createContext, createElement, useContext, useEffect, useState } from 'react'

/** Chart colours per mode. Recharts needs concrete hex values, so these mirror
 * the CSS tokens in index.css. Solar/load pair validated (CVD + contrast) on both surfaces. */
export const CHART = {
  light: {
    solar: '#eb6834', load: '#2a78d6', baseline: '#898781',
    grid: '#e1e0d9', axis: '#c3c2b7', tick: '#6f6e69', surface: '#fcfcfb', ink: '#0b0b0b', inkSecondary: '#52514e',
    waterFill: '#3987e5', waterTrack: '#cde2fb', low: '#d03b3b',
  },
  dark: {
    solar: '#d95926', load: '#3987e5', baseline: '#898781',
    grid: '#2c2c2a', axis: '#383835', tick: '#9a998f', surface: '#16181d', ink: '#ffffff', inkSecondary: '#c3c2b7',
    waterFill: '#3987e5', waterTrack: '#1c2a40', low: '#d03b3b',
  },
}

const ThemeContext = createContext(null)
const KEY = 'vtb-theme'

function readStored() {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

function systemMode() {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }) {
  const [choice, setChoice] = useState(readStored) // 'system' | 'light' | 'dark'
  const [sys, setSys] = useState(systemMode)

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const onChange = () => setSys(mq.matches ? 'dark' : 'light')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    const root = document.documentElement
    if (choice === 'system') delete root.dataset.theme
    else root.dataset.theme = choice
    try {
      if (choice === 'system') localStorage.removeItem(KEY)
      else localStorage.setItem(KEY, choice)
    } catch { /* storage blocked — theme still applies for this session */ }
  }, [choice])

  const mode = choice === 'system' ? sys : choice
  const value = { choice, setChoice, mode, chart: CHART[mode] }
  return createElement(ThemeContext.Provider, { value }, children)
}

export function useTheme() {
  return useContext(ThemeContext)
}
