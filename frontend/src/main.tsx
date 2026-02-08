import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/index.css'

/**
 * Initialize theme on application load
 * This runs before React mounts to prevent flash of unstyled content (FOUC)
 *
 * Theme priority:
 * 1. Saved theme from localStorage ('light', 'dark', or 'system')
 * 2. Default to 'system' (respects OS preference)
 */
function initializeTheme() {
  const root = document.documentElement;

  // Get saved settings from localStorage
  let savedTheme: 'light' | 'dark' | 'system' = 'system'; // Default theme

  try {
    const savedSettings = localStorage.getItem('rag-settings');
    if (savedSettings) {
      const parsed = JSON.parse(savedSettings);
      if (parsed.theme && ['light', 'dark', 'system'].includes(parsed.theme)) {
        savedTheme = parsed.theme;
      }
    }
  } catch (e) {
    // If localStorage fails, use default theme
    console.warn('Failed to read theme from localStorage:', e);
  }

  // Apply theme to document root
  if (savedTheme === 'system') {
    // Use system preference
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    root.classList.toggle('dark', prefersDark);
  } else {
    // Use explicit theme setting
    root.classList.toggle('dark', savedTheme === 'dark');
  }

  // Listen for system theme changes (when theme is set to 'system')
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    // Only respond if current setting is 'system'
    try {
      const savedSettings = localStorage.getItem('rag-settings');
      const parsed = savedSettings ? JSON.parse(savedSettings) : {};
      if (!parsed.theme || parsed.theme === 'system') {
        root.classList.toggle('dark', e.matches);
      }
    } catch {
      // Ignore parsing errors
    }
  });
}

// Initialize theme immediately (before React mounts)
initializeTheme();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
