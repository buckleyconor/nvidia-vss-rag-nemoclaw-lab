export function clock(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toISOString().slice(11, 19)
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.toISOString().slice(0, 10)} ${date.toISOString().slice(11, 16)} UTC`
}

export function timecode(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—'
  const whole = Math.max(0, Math.floor(seconds))
  const m = Math.floor(whole / 60)
  const s = whole % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function money(value: number, unit: string): string {
  const symbol = unit === 'EUR' ? '€' : unit === 'USD' ? '$' : unit === 'GBP' ? '£' : ''
  const amount = Math.round(value).toLocaleString('en-IE')
  return symbol ? `${symbol}${amount}` : `${amount} ${unit}`
}

export function range(low: number, high: number, unit: string): string {
  return `${money(low, unit)} – ${money(high, unit)}`
}

export function duration(ms: number | undefined): string {
  if (ms === undefined) return ''
  if (ms < 1000) return `${ms} ms`
  const seconds = ms / 1000
  return seconds < 60 ? `${seconds.toFixed(1)} s` : `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : ''
}
