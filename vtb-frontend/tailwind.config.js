/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: { deep: '#0D1420', panel: '#141E2E', raised: '#1B283C' },
        line: '#263449',
        text: { primary: '#E8EDF4', dim: '#7C8CA3' },
        amber: { DEFAULT: '#E8A33D', dim: '#8A6428' },
        cyan: { DEFAULT: '#4FB8C4', dim: '#2E6F77' },
        alert: { DEFAULT: '#E15252', dim: '#7A2E2E' },
      },
      fontFamily: {
        head: ['"Barlow Condensed"', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}
