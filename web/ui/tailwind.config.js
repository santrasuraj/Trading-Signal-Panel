/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (see src/index.css) so dark and light themes share one palette definition.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: v('bg'), panel: v('panel'), raised: v('raised'), line: v('line'),
        fg: v('fg'), muted: v('muted'), faint: v('faint'),
        accent: v('accent'), profit: v('profit'), loss: v('loss'), warn: v('warn'), info: v('info'),
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'Consolas', 'monospace'],
      },
      fontSize: { '2xs': ['0.6875rem', '1rem'] },
      boxShadow: { card: '0 1px 2px rgb(0 0 0 / 0.25), 0 0 0 1px rgb(var(--line) / 1)' },
    },
  },
  plugins: [],
}
