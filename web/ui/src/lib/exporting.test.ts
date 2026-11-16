import { describe, expect, it } from 'vitest'
import { rowsToCsv } from './exporting'

describe('CSV export', () => {
  it('uses every key as a column and quotes what needs it', () => {
    const csv = rowsToCsv([{ a: 1, b: 'x, y' }, { a: 2, c: { k: 1 } }])
    const lines = csv.trim().split(/\r?\n/)
    expect(lines[0]).toBe('a,b,c')
    expect(lines[1]).toBe('1,"x, y",')
    expect(lines[2]).toContain('2,,')
  })
})
