/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (see src/index.css) so dark, light and colour-blind modes share one palette definition.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: v('bg'), panel: v('panel'), raised: v('raised'), line: v('line'), 'line-strong': v('line-strong'),
        fg: v('fg'), muted: v('muted'), faint: v('faint'),
        accent: v('accent'), 'accent-strong': v('accent-strong'),
        profit: v('profit'), loss: v('loss'), warn: v('warn'), info: v('info'), violet: v('violet'),
      },
      fontFamily: {
        sans: ['"Inter Variable"', 'Inter', 'system-ui', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['11px', '16px'],
        xs: ['12px', '16px'],
        sm: ['13px', '20px'],
        base: ['14px', '22px'],
        lg: ['16px', '24px'],
        xl: ['20px', '28px'],
        '2xl': ['24px', '30px'],
        '3xl': ['28px', '34px'],
      },
      height: { row: 'var(--row-h)' },
      boxShadow: { pop: 'var(--shadow-pop)' },
      screens: { '3xl': '1440px' },
    },
  },
  plugins: [],
}
