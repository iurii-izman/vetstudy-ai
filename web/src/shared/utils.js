export function cx(...classes) {
  return classes.filter(Boolean).join(' ')
}

export function formatDate(value) {
  if (!value) return 'n/a'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'n/a'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function shortId(value) {
  return value ? String(value).slice(0, 8) : 'none'
}
