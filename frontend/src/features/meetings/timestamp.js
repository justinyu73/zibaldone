// 摘要離散項帶 [mm:ss] 錨（quote+timestamp distill）；拆成乾淨文字 + 膠囊。
// 模型有時把 [mm:ss] 放開頭/結尾、甚至塞多個（小模型品質問題）——取第一個當膠囊、
// 去掉文字裡所有 [mm:ss]，避免漏標/重複。無時碼則 ts:null、只渲染文字。
export function splitTimestamp(item) {
  const s = String(item)
  const pattern = /[\[【（(](\d{1,2}:\d{2})[\]】）)]/
  const m = s.match(pattern)
  const text = s.replace(/\s*[\[【（(]\d{1,2}:\d{2}[\]】）)]\s*/g, ' ').trim()
  return m ? { text, ts: m[1] } : { text: s, ts: null }
}

// "m:ss" / "mm:ss" → 秒。用於點膠囊跳回音檔。格式不符回 null（不可跳）。
export function tsToSeconds(ts) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(ts || '')
  return m ? Number(m[1]) * 60 + Number(m[2]) : null
}
