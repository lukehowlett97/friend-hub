export function openNativeDatePicker(event) {
  const input = event.currentTarget;
  if (typeof input.showPicker !== 'function') return;
  try {
    input.showPicker();
  } catch {
    // Browsers only allow showPicker during trusted user gestures.
  }
}
