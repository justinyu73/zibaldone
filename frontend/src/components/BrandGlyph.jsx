// Provider/brand LOGO glyph (hand-drawn approximations, not official marks).
// Accepts a provider key (openai/anthropic/google) or a brand name.
export function brandGlyphKey(name) {
  const b = String(name || '').toLowerCase()
  if (b.includes('claude') || b.includes('anthropic')) return 'claude'
  if (b.includes('openai') || b.includes('gpt')) return 'openai'
  if (b.includes('gemini') || b.includes('google')) return 'gemini'
  if (b.includes('ollama') || b.includes('llama') || b.includes('qwen')) return 'ollama'
  return 'generic'
}

const GLYPHS = {
  claude: <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M12 2c.5 3.4 2 5.4 4.5 6.2C14 9 12.5 11 12 14c-.5-3-2-5-4.5-5.8C10 7.4 11.5 5.4 12 2z" /></svg>,
  gemini: <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M12 2c.6 5.2 4.2 8.8 10 9.4C16.2 12 12.6 15.6 12 22c-.6-6.4-4.2-10-10-10.6C7.8 10.8 11.4 7.2 12 2z" /></svg>,
  openai: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13"><circle cx="12" cy="12" r="5" /></svg>,
  ollama: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13"><rect x="5" y="9" width="14" height="10" rx="2" /></svg>,
  generic: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13"><circle cx="12" cy="12" r="9" /></svg>,
}

export default function BrandGlyph({ provider, brand, className = '' }) {
  const key = brandGlyphKey(provider ?? brand)
  return <span className={`brand-glyph bg-${key} ${className}`.trim()} aria-hidden="true">{GLYPHS[key]}</span>
}
