/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (see src/index.css) so light/dark swap in one place.
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        page: 'var(--page)',
        surface: 'var(--surface)',
        raised: 'var(--raised)',
        line: 'var(--line)',
        ink: {
          DEFAULT: 'var(--ink)',
          secondary: 'var(--ink-secondary)',
          muted: 'var(--ink-muted)',
        },
        accent: { DEFAULT: 'var(--accent)', soft: 'var(--accent-soft)' },
        solar: { DEFAULT: 'var(--solar)', soft: 'var(--solar-soft)' },
        good: { DEFAULT: 'var(--good)', text: 'var(--good-text)', soft: 'var(--good-soft)' },
        warning: { DEFAULT: 'var(--warning)', text: 'var(--warning-text)', soft: 'var(--warning-soft)' },
        critical: { DEFAULT: 'var(--critical)', text: 'var(--critical-text)', soft: 'var(--critical-soft)' },
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
      borderRadius: { card: '14px' },
    },
  },
  plugins: [],
}
