export function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat('en-US').format(value ?? 0)
}

export function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'Unavailable'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: value < 1 ? 4 : 2,
  }).format(value)
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'Unavailable'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unavailable'
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    hourCycle: 'h23',
  }).format(date)
}

export function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return 'Unavailable'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unavailable'
  const seconds = Math.round((date.getTime() - Date.now()) / 1000)
  const ranges: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['day', 60 * 60 * 24],
    ['hour', 60 * 60],
    ['minute', 60],
    ['second', 1],
  ]
  for (const [unit, unitSeconds] of ranges) {
    if (Math.abs(seconds) >= unitSeconds || unit === 'second') {
      return new Intl.RelativeTimeFormat('en-US', { numeric: 'auto' }).format(
        Math.round(seconds / unitSeconds),
        unit,
      )
    }
  }
  return 'Unavailable'
}

export function formatLatencyValue(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'Unavailable'
  if (value < 1) {
    return `${Math.round(value * 1000)}ms`
  }
  if (value < 60) {
    return `${value < 10 ? value.toFixed(2) : value.toFixed(1)}s`
  }
  if (value < 3600) {
    return `${(value / 60).toFixed(value < 600 ? 1 : 0)}m`
  }
  if (value < 86400) {
    return `${(value / 3600).toFixed(value < 36000 ? 1 : 0)}h`
  }
  return `${(value / 86400).toFixed(value < 864000 ? 1 : 0)}d`
}

export function formatSourceLabel(value: string): string {
  return value === 'truth_social' ? 'Truth Social' : value.toUpperCase()
}

export function formatStatusLabel(value: string): string {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}
