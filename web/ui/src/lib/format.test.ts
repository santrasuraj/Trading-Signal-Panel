import { describe, expect, it } from 'vitest'
import {
  DASH, MINUS, date, dateTimeIST, daysBetween, daysUntil, duration, money, moneyCompact, num, parseISODate, pct, price, pts,
  qty, ratio, relative, timeIST, todayIST, tone,
} from './format'

describe('price', () => {
  it('uses Indian grouping and 2 dp', () => {
    expect(price(123456.78)).toBe('1,23,456.78')
    expect(price(22687.65)).toBe('22,687.65')
    expect(price(353.2)).toBe('353.20')
    expect(price(12345678.9)).toBe('1,23,45,678.90')
  })
  it('uses the unicode minus', () => {
    expect(price(-5.5)).toBe(`${MINUS}5.50`)
  })
  it('never prints negative zero', () => {
    expect(price(-0.001)).toBe('0.00')
  })
  it('renders missing values as an em dash', () => {
    expect(price(null)).toBe(DASH)
    expect(price(undefined)).toBe(DASH)
    expect(price(NaN)).toBe(DASH)
    expect(price(Infinity)).toBe(DASH)
  })
})

describe('money', () => {
  it('formats whole rupees with Indian grouping', () => {
    expect(money(500000)).toBe('₹5,00,000')
    expect(money(49801.2)).toBe('₹49,801')
    expect(money(123456.78, { dp: 2 })).toBe('₹1,23,456.78')
  })
  it('signs', () => {
    expect(money(12340, { signed: true })).toBe('+₹12,340')
    expect(money(-5000)).toBe(`${MINUS}₹5,000`)
    expect(money(-5000, { signed: true })).toBe(`${MINUS}₹5,000`)
    expect(money(0, { signed: true })).toBe('₹0')
  })
  it('handles null', () => expect(money(null)).toBe(DASH))
})

describe('moneyCompact', () => {
  it('uses lakh and crore', () => {
    expect(moneyCompact(500000)).toBe('₹5.00 L')
    expect(moneyCompact(12500000)).toBe('₹1.25 Cr')
    expect(moneyCompact(-250000)).toBe(`${MINUS}₹2.50 L`)
    expect(moneyCompact(99999)).toBe('₹99,999')
    expect(moneyCompact(150000, { signed: true })).toBe('+₹1.50 L')
  })
})

describe('pct / pts / ratio / qty / num', () => {
  it('pct is signed with 1 dp by default', () => {
    expect(pct(12.44)).toBe('+12.4%')
    expect(pct(-3.2, { dp: 2 })).toBe(`${MINUS}3.20%`)
    expect(pct(42.335, { signed: false })).toBe('42.3%')
    expect(pct(0)).toBe('0.0%')
    expect(pct(-0.01)).toBe('0.0%')
    expect(pct(1100.244)).toBe('+1,100.2%')
    expect(pct(null)).toBe(DASH)
  })
  it('pts', () => {
    expect(pts(14.9)).toBe('+14.9')
    expect(pts(-9.53)).toBe(`${MINUS}9.5`)
    expect(pts(0.01)).toBe('0.0')
  })
  it('ratio', () => {
    expect(ratio(1.624)).toBe('1.62')
    expect(ratio(-2.86)).toBe(`${MINUS}2.86`)
  })
  it('qty', () => {
    expect(qty(4866)).toBe('4,866')
    expect(qty(150000)).toBe('1,50,000')
    expect(qty(null)).toBe(DASH)
  })
  it('num', () => {
    expect(num(15.76)).toBe('15.76')
    expect(num(7.711, 1)).toBe('7.7')
  })
  it('tone', () => {
    expect(tone(1)).toBe('profit')
    expect(tone(-1)).toBe('loss')
    expect(tone(0)).toBe('flat')
    expect(tone(null)).toBe('flat')
  })
})

describe('dates', () => {
  it('parses ISO dates without timezone shifts', () => {
    expect(parseISODate('2026-10-22')).toEqual({ y: 2026, m: 10, d: 22 })
    expect(parseISODate('bad')).toBeNull()
    expect(date('2026-10-22')).toBe('22 Oct 2026')
    expect(date('2026-01-01', { year: false })).toBe('1 Jan')
    expect(date(null)).toBe(DASH)
  })
  it('formats IST times', () => {
    expect(timeIST('2026-10-23T09:18:47+05:30')).toBe('09:18 IST')
    expect(timeIST('2026-10-23T03:48:47Z', { suffix: false })).toBe('09:18')
    expect(dateTimeIST('2026-10-23T09:18:47+05:30')).toContain('23 Oct 2026')
  })
  it('relative times', () => {
    const now = new Date('2026-10-23T18:18:47+05:30').getTime()
    expect(relative('2026-10-23T09:18:47+05:30', now)).toBe('9 h ago')
    expect(relative('2026-10-23T18:15:47+05:30', now)).toBe('3 min ago')
    expect(relative('2026-10-23T18:18:40+05:30', now)).toBe('just now')
  })
  it('durations and countdowns', () => {
    expect(duration(11.6)).toBe('11.6 s')
    expect(duration(122.1)).toBe('2 min 2 s')
    expect(daysUntil(0)).toBe('today')
    expect(daysUntil(5)).toBe('in 5 d')
  })
  it('day arithmetic', () => {
    expect(daysBetween('2026-10-22', '2026-10-30')).toBe(8)
    expect(daysBetween('2026-12-31', '2027-01-01')).toBe(1)
    expect(todayIST(new Date('2026-10-22T20:00:00Z'))).toBe('2026-10-23')
  })
})
