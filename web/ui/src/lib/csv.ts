/** Client-side CSV export of raw (unformatted) values. */
export function toCsv(headers: string[], rows: unknown[][]): string {
  const esc = (v: unknown) => {
    if (v == null) return ''
    const s = Array.isArray(v) ? v.join(' ') : String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  return [headers.map(esc).join(','), ...rows.map((r) => r.map(esc).join(','))].join('\n')
}

export function downloadText(filename: string, text: string, type = 'text/csv;charset=utf-8') {
  // a UTF-8 byte-order mark makes Excel on Windows read "Buy ₹" instead of "Buy â‚¹"
  const BOM = String.fromCharCode(0xfeff)
  const body = type.startsWith('text/csv') && !text.startsWith(BOM) ? `${BOM}${text}` : text
  const blob = new Blob([body], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const cn = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(' ')
