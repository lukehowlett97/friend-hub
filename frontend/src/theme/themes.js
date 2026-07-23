export const THEME_STORAGE_KEY = 'friendHub.themeId';

function svgPattern(svgContent) {
  return `data:image/svg+xml,${encodeURIComponent(svgContent)}`;
}

export const themes = [
  {
    id: 'classic-hub',
    name: 'Classic Hub',
    description: 'Clean, social, and balanced.',
    colours: {
      background: '#edf2f7',
      surface: '#fffaf5',
      surfaceAlt: '#f7f9fc',
      primary: '#5168d9',
      primaryText: '#ffffff',
      accent: '#f9734d',
      text: '#172033',
      mutedText: '#687386',
      border: '#dfe7f2',
      navBackground: '#111827',
      ownMessage: '#5168d9',
      botMessage: '#e9f1ff',
    },
  },
  {
    id: 'night-out',
    name: 'Night Out',
    description: 'Dark, warm, and made for late plans.',
    colours: {
      background: '#0f172a',
      surface: '#172033',
      surfaceAlt: '#202b42',
      primary: '#8b5cf6',
      primaryText: '#ffffff',
      accent: '#fbbf24',
      text: '#f8fafc',
      mutedText: '#c7d2fe',
      border: '#334155',
      navBackground: '#070b16',
      ownMessage: '#7c3aed',
      botMessage: '#263451',
    },
  },
  {
    id: 'soft-pastel',
    name: 'Soft Pastel',
    description: 'Light, casual, and gentle.',
    colours: {
      background: '#fff1f4',
      surface: '#fffdfb',
      surfaceAlt: '#f7efff',
      primary: '#8b7cf6',
      primaryText: '#ffffff',
      accent: '#fb7185',
      text: '#263244',
      mutedText: '#6f7585',
      border: '#eadde8',
      navBackground: '#322b4f',
      ownMessage: '#8b7cf6',
      botMessage: '#f1eaff',
    },
  },
  {
    id: 'forest',
    name: 'Forest',
    description: 'Calm, earthy, and grounded.',
    colours: {
      background: '#eaf3e8',
      surface: '#fffdf7',
      surfaceAlt: '#f0f7ed',
      primary: '#2f6b4f',
      primaryText: '#ffffff',
      accent: '#d9912b',
      text: '#213529',
      mutedText: '#61715f',
      border: '#d7e3d2',
      navBackground: '#183326',
      ownMessage: '#2f6b4f',
      botMessage: '#e3f1dc',
    },
  },
  {
    id: 'retro',
    name: 'Retro',
    description: 'Warm, playful, and a little nostalgic.',
    colours: {
      background: '#fbf0d8',
      surface: '#fff8e8',
      surfaceAlt: '#edf0df',
      primary: '#3f6f8f',
      primaryText: '#ffffff',
      accent: '#c75b2c',
      text: '#2c2430',
      mutedText: '#695d55',
      border: '#e5d3b4',
      navBackground: '#233041',
      ownMessage: '#3f6f8f',
      botMessage: '#e8efe7',
    },
  },
  {
    id: 'steel',
    name: 'Steel',
    description: 'Cool, industrial, and focused.',
    colours: {
      background: '#0b1120',
      surface: '#141c30',
      surfaceAlt: '#1c2742',
      primary: '#5b8dee',
      primaryText: '#ffffff',
      accent: '#3bc9db',
      text: '#e2e8f0',
      mutedText: '#8899b4',
      border: '#1e2d4a',
      navBackground: '#070c17',
      ownMessage: '#5b8dee',
      botMessage: '#17223b',
    },
    backgroundPattern: svgPattern(
      `<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" viewBox="0 0 60 60">
        <path d="M 0 0 L 60 60 M 60 0 L 0 60" stroke="#5b8dee" stroke-width="0.4" opacity="0.06" fill="none"/>
        <circle cx="0" cy="0" r="1.2" fill="#3bc9db" opacity="0.05"/>
        <circle cx="60" cy="60" r="1.2" fill="#3bc9db" opacity="0.05"/>
        <circle cx="30" cy="30" r="0.8" fill="#5b8dee" opacity="0.04"/>
      </svg>`
    ),
  },
  {
    id: 'obsidian',
    name: 'Obsidian',
    description: 'Deep, sharp, and grounded.',
    colours: {
      background: '#0a0a0f',
      surface: '#14141e',
      surfaceAlt: '#1e1e2c',
      primary: '#a78bfa',
      primaryText: '#ffffff',
      accent: '#f59e0b',
      text: '#e4e4ed',
      mutedText: '#8b8ba0',
      border: '#252536',
      navBackground: '#050508',
      ownMessage: '#7c5cfc',
      botMessage: '#1b1b2a',
    },
    backgroundPattern: svgPattern(
      `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">
        <circle cx="10" cy="10" r="0.7" fill="#a78bfa" opacity="0.07"/>
      </svg>`
    ),
  },
  {
    id: 'mineral',
    name: 'Mineral',
    description: 'Sharp, clean, and undisturbed.',
    colours: {
      background: '#f0f3f8',
      surface: '#ffffff',
      surfaceAlt: '#f4f7fc',
      primary: '#3b6ea5',
      primaryText: '#ffffff',
      accent: '#0d9488',
      text: '#1e293b',
      mutedText: '#64748b',
      border: '#dce3ed',
      navBackground: '#0f172a',
      ownMessage: '#3b6ea5',
      botMessage: '#e6edf6',
    },
    backgroundPattern: svgPattern(
      `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40">
        <rect width="40" height="40" fill="none"/>
        <path d="M 0 10 L 40 10 M 0 20 L 40 20 M 0 30 L 40 30 M 10 0 L 10 40 M 20 0 L 20 40 M 30 0 L 30 40" stroke="#3b6ea5" stroke-width="0.3" opacity="0.04" fill="none"/>
        <circle cx="10" cy="10" r="1" fill="#0d9488" opacity="0.04"/>
        <circle cx="20" cy="20" r="1" fill="#0d9488" opacity="0.04"/>
        <circle cx="30" cy="30" r="1" fill="#0d9488" opacity="0.04"/>
      </svg>`
    ),
  },
];

export const defaultThemeId = 'classic-hub';

export function getThemeById(themeId) {
  return themes.find((theme) => theme.id === themeId) || themes[0];
}