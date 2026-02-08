/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Light theme colors
        light: {
          bg: '#FFFFFF',
          sidebar: '#F7F7F8',
          text: '#1A1A1A',
          'text-secondary': '#6B6B6B',
          border: '#E5E5E5',
        },
        // Dark theme colors
        dark: {
          bg: '#212121',
          sidebar: '#171717',
          text: '#ECECEC',
          'text-secondary': '#8E8E8E',
          border: '#2F2F2F',
        },
        // Primary accent color (WCAG AA compliant - 4.5:1+ contrast with white)
        primary: {
          DEFAULT: '#047857',  // Changed from #10A37F (3.2:1) to #047857 (5.5:1) for WCAG AA compliance
          hover: '#065f46',    // Darker hover state
          light: '#D1FAE5',
          // Keep original for non-text uses like backgrounds with dark text
          original: '#10A37F',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
