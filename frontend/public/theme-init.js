// Sets data-theme on <html> before the first paint (design D-2).
// Kept as an external synchronous script: the CSP (script-src 'self') forbids inline scripts.
(function () {
  var theme = 'dark'
  try {
    var saved = localStorage.getItem('fim.theme')
    if (saved === 'light' || saved === 'dark') {
      theme = saved
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
      theme = 'light'
    }
  } catch (e) {
    // Storage may be blocked: fall back to the system preference or dark.
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) theme = 'light'
  }
  document.documentElement.setAttribute('data-theme', theme)
})()
