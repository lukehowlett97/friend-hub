export const haptic = (pattern = 10) => {
  if (navigator.vibrate) navigator.vibrate(pattern);
};
