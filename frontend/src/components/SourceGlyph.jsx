// Shared source-type glyph: colored icon standing in for a text label.
// type: article | audio | video | doc（未知退回 doc）
const ICONS = {
  article: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M9 13h6M9 17h4" />
    </svg>
  ),
  audio: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3" />
    </svg>
  ),
  video: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m10 8 6 4-6 4z" /><rect x="2" y="4" width="20" height="16" rx="3" />
    </svg>
  ),
  doc: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" />
    </svg>
  ),
}

// vault 相對路徑推導來源型態（不臆測、僅依既有資料夾慣例）。
export function sourceTypeFromPath(path = '') {
  const p = String(path).toLowerCase()
  if (p.includes('/youtube') || p.endsWith('.mp4')) return 'video'
  if (p.includes('/audio') || p.includes('/meeting') || p.endsWith('.m4a') || p.endsWith('.mp3')) return 'audio'
  return 'article'
}

export default function SourceGlyph({ type = 'doc', className = '' }) {
  const key = ICONS[type] ? type : 'doc'
  return <span className={`src-glyph sg-${key} ${className}`.trim()} aria-hidden="true">{ICONS[key]}</span>
}
