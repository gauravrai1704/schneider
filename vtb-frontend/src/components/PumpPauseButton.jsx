import { useState } from 'react'
import { IconPause, IconPlay } from './icons'

/** One-tap DISCOM demand response. Big, unmistakable, and it says what it will do. */
export default function PumpPauseButton({ paused, onToggle }) {
  const [busy, setBusy] = useState(false)
  const click = async () => {
    setBusy(true)
    try { await onToggle(!paused) } finally { setBusy(false) }
  }
  return (
    <button
      onClick={click}
      disabled={busy}
      className={`flex w-full items-center justify-center gap-2 rounded-card px-5 py-4 text-base font-semibold text-white shadow-sm transition active:scale-[0.98] disabled:opacity-60 ${
        paused ? 'bg-accent hover:brightness-110' : 'bg-critical hover:brightness-110'
      }`}
    >
      {paused ? <IconPlay width={18} height={18} /> : <IconPause width={18} height={18} />}
      {busy ? 'Sending…' : paused ? 'Resume all pumps' : 'Pause all pumps'}
    </button>
  )
}
