const WEEKDAYS = '日月火水木金土'

/** ISO 文字列を `<input type="datetime-local">` 用の 'YYYY-MM-DDTHH:MM'（ローカル時刻）にする。 */
export function toLocalInput(value: string | Date): string {
  const d = typeof value === 'string' ? new Date(value) : value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatDay(value: string): string {
  const d = new Date(value.length === 10 ? `${value}T00:00` : value)
  return `${d.getMonth() + 1}/${d.getDate()}（${WEEKDAYS[d.getDay()]}）`
}

function hm(value: string): string {
  const d = new Date(value)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 予定の日時を「11/3（月） 10:00〜11:00」「11/3（月） 終日」の形で表示する。 */
export function formatRange(item: { all_day: boolean; start: string; end: string }): string {
  if (item.all_day) {
    return item.start === item.end ? `${formatDay(item.start)} 終日` : `${formatDay(item.start)}〜${formatDay(item.end)} 終日`
  }
  const sameDay = item.start.slice(0, 10) === item.end.slice(0, 10)
  return sameDay
    ? `${formatDay(item.start)} ${hm(item.start)}〜${hm(item.end)}`
    : `${formatDay(item.start)} ${hm(item.start)}〜${formatDay(item.end)} ${hm(item.end)}`
}

export function dayKey(value: string): string {
  return value.length === 10 ? value : toLocalInput(value).slice(0, 10)
}
