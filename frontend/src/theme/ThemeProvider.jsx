import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { THEME_STORAGE_KEY, defaultThemeId, getThemeById, themes } from './themes.js';

const ThemeContext = createContext(null);

function readStoredThemeId() {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) || defaultThemeId;
  } catch {
    return defaultThemeId;
  }
}

function toCssVariables(theme) {
  const vars = Object.entries(theme.colours).reduce((acc, [key, value]) => {
    const cssKey = key.replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`);
    acc[`--color-${cssKey}`] = value;
    return acc;
  }, {});
  if (theme.backgroundPattern) {
    vars['--background-pattern'] = `url("${theme.backgroundPattern}")`;
  } else {
    vars['--background-pattern'] = 'none';
  }
  return vars;
}

export function ThemeProvider({ children }) {
  const [themeId, setThemeId] = useState(readStoredThemeId);
  const theme = getThemeById(themeId);

  useEffect(() => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme.id);
    } catch {
      // localStorage may be unavailable in private contexts.
    }
  }, [theme.id]);

  const value = useMemo(() => ({
    theme,
    themeId: theme.id,
    themes,
    setThemeId,
  }), [theme]);

  return (
    <ThemeContext.Provider value={value}>
      <div className="app-theme-root" data-theme={theme.id} style={toCssVariables(theme)}>
        {children}
      </div>
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error('useTheme must be used within ThemeProvider');
  return value;
}
