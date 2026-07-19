export function newerVersion(candidate, current) {
  function parseParts(v) {
    const parts = String(v).replace(/^[vV]/, '').split('.')
    const nums = parts.map(p => (/^\d+$/.test(p) ? Number(p) : null))
    return nums.some(n => n === null) ? null : nums
  }

  const next = parseParts(candidate)
  const installed = parseParts(current)
  if (next === null || installed === null) return false

  for (let index = 0; index < 3; index += 1) {
    const a = next[index] ?? 0
    const b = installed[index] ?? 0
    if (a !== b) return a > b
  }
  return false
}
