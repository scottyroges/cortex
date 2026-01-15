/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'type-note': '#06b6d4',
        'type-insight': '#f59e0b',
        'type-commit': '#22c55e',
        'type-initiative': '#a855f7',
        'type-code': '#3b82f6',
      },
    },
  },
  plugins: [],
}
