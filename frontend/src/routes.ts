export interface RouteDef {
  id: string
  label: string
  /** 未実装の画面は実装予定フェーズを示す（モックと実機能を区別するため） */
  plannedPhase?: number
}

export const ROUTES: RouteDef[] = [
  { id: 'chat', label: 'チャット' },
  { id: 'voice', label: '音声会話' },
  { id: 'avatar', label: '3Dアバター' },
  { id: 'memory', label: '記憶管理' },
  { id: 'calendar', label: 'カレンダー' },
  { id: 'training', label: '学習管理' },
  { id: 'settings', label: '設定' },
]
