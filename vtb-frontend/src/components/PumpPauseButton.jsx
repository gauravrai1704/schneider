/** Styled like a physical emergency-stop button rather than a generic
 * rounded UI button — this is literally what it does (cuts all pumps). */
export default function PumpPauseButton({ paused, onToggle }) {
  return (
    <button
      onClick={() => onToggle(!paused)}
      className="flex flex-col items-center gap-2 group"
    >
      <span
        className="w-20 h-20 rounded-full flex items-center justify-center transition-transform active:scale-95"
        style={{
          background: paused ? '#7A2E2E' : '#E15252',
          boxShadow: paused
            ? 'inset 0 3px 6px rgba(0,0,0,0.5)'
            : '0 4px 0 #8f1f1f, 0 6px 10px rgba(0,0,0,0.4)',
        }}
      >
        <span className="w-14 h-14 rounded-full border-2 border-white/30" />
      </span>
      <span className="panel-label text-sm text-text-primary">
        {paused ? 'pumps paused — resume' : 'pump pause'}
      </span>
    </button>
  )
}
