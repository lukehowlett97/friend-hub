// Eight visually distinct colours used for user avatars and nickname labels.
// Chosen for good contrast on both white and dark bubble backgrounds.
const PALETTE = [
  '#e74c3c', // red
  '#9b59b6', // purple
  '#3498db', // blue
  '#1abc9c', // teal
  '#f39c12', // orange
  '#e67e22', // dark orange
  '#2ecc71', // green
  '#e91e63', // pink
];

/**
 * Map a nickname to a stable colour from PALETTE.
 * The same string always produces the same colour across sessions and tabs.
 *
 * @param {string} nickname
 * @returns {string} hex colour, e.g. "#3498db"
 */
export function getColorForNickname(nickname) {
  if (!nickname) return PALETTE[0];
  let hash = 0;
  for (let i = 0; i < nickname.length; i++) {
    hash = nickname.charCodeAt(i) + ((hash << 5) - hash);
  }
  return PALETTE[Math.abs(hash) % PALETTE.length];
}
