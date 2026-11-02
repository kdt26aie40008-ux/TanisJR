import type { MemoryCategory } from '../api/types'

export const CATEGORY_LABELS: Record<MemoryCategory, string> = {
  preference: '好み',
  habit: '習慣・傾向',
  fact: '事実',
  personal: '個人情報',
  personality: '性格',
  values: '価値観',
  other: 'その他',
}

export const CATEGORIES = Object.keys(CATEGORY_LABELS) as MemoryCategory[]

export function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('ja-JP')
}
