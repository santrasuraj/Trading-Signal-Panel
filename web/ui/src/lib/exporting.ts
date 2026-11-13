// Download any table as a CSV file that Excel opens directly (UTF-8 with a byte-order mark, so ₹ and names survive).

import { downloadText, toCsv } from '@/lib/csv'

export function rowsToCsv(rows: Record<string, unknown>[]): string {
  const headers = [...new Set(rows.flatMap((r) => Object.keys(r)))]
  return toCsv(headers, rows.map((r) => headers.map((h) => {
    const v = r[h]
    return v != null && typeof v === 'object' ? JSON.stringify(v) : v
  })))
}

export function downloadCsv(filename: string, rows: Record<string, unknown>[]): void {
  downloadText(filename, rowsToCsv(rows))   // downloadText adds Excel's byte-order mark
}
