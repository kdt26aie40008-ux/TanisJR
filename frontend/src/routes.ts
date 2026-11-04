import { BookHeart, CalendarDays, MessageCircleHeart, Settings2, Sparkles, Sprout, type LucideIcon } from 'lucide-react'

export type SectionId = 'chat' | 'avatar' | 'memory' | 'calendar' | 'training' | 'settings'

export interface RouteDef {
  id: SectionId
  label: string
  icon: LucideIcon
  /** 未実装の画面は実装予定フェーズを示す（モックと実機能を区別するため） */
  plannedPhase?: number
}

// 画面ごとの色は styles.css の [data-section] で決める
export const ROUTES: RouteDef[] = [
  { id: 'chat', label: 'おしゃべり', icon: MessageCircleHeart },
  { id: 'calendar', label: '予定', icon: CalendarDays },
  { id: 'memory', label: '思い出', icon: BookHeart },
  { id: 'avatar', label: 'すがた', icon: Sparkles },
  { id: 'training', label: '成長', icon: Sprout },
  { id: 'settings', label: '設定', icon: Settings2 },
]
