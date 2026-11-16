import { describe, expect, it } from 'vitest'
import { provenance, sourceLabel, type HeatProvenance } from './heatmap'

const base: HeatProvenance = { session: 'open', sources: {}, quotes_from: null, quotes_to: null, refreshing: false, scan_date: '2026-11-13' }

describe('heatmap provenance line', () => {
  it('counts each source, flags an earlier day scan in the session, and gives the quotes time', () => {
    const parts = provenance({ ...base, sources: { live: 1, yahoo: 300, scan: 179 }, quotes_from: '2026-11-16T12:22:05+05:30',
      quotes_to: '2026-11-16T12:25:40+05:30', refreshing: true }, '2026-11-16')
    expect(parts.map((p) => p.text)).toEqual(['1 live feed', '300 Yahoo (~15 min late)', '179 from the 13 Nov scan',
      'quotes from 12:22–12:25 IST', 'refreshing…'])
    expect(parts.filter((p) => p.warn).map((p) => p.text)).toEqual(['179 from the 13 Nov scan'])
  })

  it('after 18:00 (or with a scan of today) the scan is the day itself: no flag, no quote time', () => {
    const closed = provenance({ ...base, session: 'closed', sources: { scan: 480 }, scan_date: '2026-11-16' }, '2026-11-16')
    expect(closed).toEqual([{ text: '480 from the 16 Nov scan', warn: false }])
    const post = provenance({ ...base, session: 'post_close', sources: { scan: 2 }, scan_date: '2026-11-16' }, '2026-11-16')
    expect(post[0].warn).toBe(false)
  })

  it('labels one stock for its tooltip', () => {
    expect(sourceLabel('yahoo', null)).toBe('Yahoo, ~15 min late')
    expect(sourceLabel('scan', '2026-11-13')).toBe('last scan (13 Nov)')
    expect(sourceLabel(undefined, null)).toBe('last scan')
  })
})
