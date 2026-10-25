(async () => {
  const status = document.getElementById('docs-status');
  try {
    const response = await fetch('/openapi.json', { signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error(`API description returned HTTP ${response.status}`);
    const content = await response.json();
    Scalar.createApiReference('#docs-reference', {
      content,
      theme: 'none',
      withDefaultFonts: false,
      darkMode: true,
      hideDarkModeToggle: true,
      defaultHttpClient: { targetKey: 'shell', clientKey: 'curl' },
    });
    status.remove();
  } catch (error) {
    status.textContent = 'Documentation could not load. Please reload this page.';
    console.error('Documentation initialization failed:', error);
  }
})();
