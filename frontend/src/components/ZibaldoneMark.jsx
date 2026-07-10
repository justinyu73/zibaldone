// Zibaldone 標誌（Notebook-Z）：Z 字＋左側活頁裝訂孔，呼應「雜記本」。
// badge 以 var(--brand) 上色，隨主題換（淺=磚橘、深=青綠）。
export default function ZibaldoneMark({ className = '', title = 'Zibaldone' }) {
  return (
    <svg className={className} viewBox="0 0 96 96" role="img" aria-label={title}>
      <rect x="4" y="4" width="88" height="88" rx="24" fill="var(--brand)" />
      <g fill="#fff" opacity="0.9">
        <circle cx="27" cy="34" r="3.4" />
        <circle cx="27" cy="48" r="3.4" />
        <circle cx="27" cy="62" r="3.4" />
      </g>
      <path d="M38 32 H67 L41 64 H69" fill="none" stroke="#fff" strokeWidth="8.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
