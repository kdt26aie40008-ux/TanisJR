import { lazy, Suspense } from 'react'
import { api } from '../../api/client'
import type { Avatar } from '../../api/types'
import type { Emotion } from '../../lib/emotion'
import type { Activity } from './AvatarViewer'

// three.js 一式は大きいので、アバターを表示するときだけ読み込む
const AvatarViewer = lazy(() => import('./AvatarViewer'))

interface Props {
  avatar: Avatar | null
  getLevel?: () => number
  emotion?: Emotion
  activity?: Activity
  nod?: boolean
  getListenLevel?: () => number
  gaze?: boolean
  framing?: 'close' | 'wide'
  emptyMessage?: React.ReactNode
}

/** アバター表示領域。仮モデルの表示と、必要なクレジット表記を必ず添える。 */
export function AvatarStage({ avatar, getLevel, emotion, activity, nod, getListenLevel, gaze, framing, emptyMessage }: Props) {
  if (!avatar) {
    return (
      <div className="avatar-stage empty">
        <p className="hint">{emptyMessage ?? 'アバターが設定されていません。'}</p>
      </div>
    )
  }
  return (
    <div className="avatar-stage">
      {avatar.is_placeholder && (
        <span className="placeholder-badge" title="正式なモデルではありません">
          仮モデル
        </span>
      )}
      <Suspense fallback={<div className="avatar-overlay">3D表示を準備中…</div>}>
        <AvatarViewer
          url={api.avatarFileUrl(avatar.id)}
          getLevel={getLevel}
          emotion={emotion}
          activity={activity}
          nod={nod}
          getListenLevel={getListenLevel}
          gaze={gaze}
          framing={framing}
        />
      </Suspense>
      {(avatar.meta.credit_required || avatar.meta.authors) && (
        <p className="avatar-credit">
          {avatar.meta.name || avatar.name}
          {avatar.meta.authors && ` / 作者: ${avatar.meta.authors}`}
        </p>
      )}
    </div>
  )
}
