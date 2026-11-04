import { useState } from 'react'
import { api, errorMessage } from '../../api/client'
import type { CalendarOperation, EventDraft } from '../../api/types'
import { formatRange } from '../../lib/datetime'

const ACTION_LABELS = { create: '予定の追加', update: '予定の変更', delete: '予定の削除' } as const
const STATUS_LABELS = { pending: '承認待ち', done: '実行しました', rejected: '却下しました', failed: '失敗しました' } as const

function DraftDetails({ draft }: { draft: EventDraft }) {
  return (
    <dl className="summary compact">
      <div>
        <dt>タイトル</dt>
        <dd>{draft.summary}</dd>
      </div>
      <div>
        <dt>日時</dt>
        <dd>{formatRange(draft)}</dd>
      </div>
      {draft.location && (
        <div>
          <dt>場所</dt>
          <dd>{draft.location}</dd>
        </div>
      )}
      {draft.reminder_minutes != null && (
        <div>
          <dt>通知</dt>
          <dd>{draft.reminder_minutes}分前</dd>
        </div>
      )}
    </dl>
  )
}

interface Props {
  operation: CalendarOperation
  onChanged?: (op: CalendarOperation) => void
}

/**
 * カレンダー操作の確認カード。「承認して実行」を押したときだけ Google カレンダーに反映される。
 * AI の提案もこのカードを通るため、AI の発言だけで予定が変わることはない。
 */
export function OperationCard({ operation, onChanged }: Props) {
  const [op, setOp] = useState(operation)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const decide = async (approve: boolean) => {
    if (approve && op.action === 'delete' && !window.confirm(`「${op.target?.summary ?? '予定'}」を Google カレンダーから削除します。よろしいですか？`)) {
      return
    }
    setBusy(true)
    setError('')
    try {
      const next = approve ? await api.approveCalendarOperation(op.id) : await api.rejectCalendarOperation(op.id)
      setOp(next)
      onChanged?.(next)
    } catch (err) {
      setError(errorMessage(err))
      // 失敗した場合も最新の状態を取得する
      try {
        const latest = (await api.calendarOperations('all')).find((o) => o.id === op.id)
        if (latest) {
          setOp(latest)
          onChanged?.(latest)
        }
      } catch {
        // 表示はエラーメッセージで十分
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`operation-card panel status-${op.status}`} role="group" aria-label={ACTION_LABELS[op.action]}>
      <div className="memory-head">
        <strong>{ACTION_LABELS[op.action]}</strong>
        <span className={`tag${op.source === 'ai' ? ' important' : ''}`}>{op.source === 'ai' ? '会話からの提案' : 'あなたの入力'}</span>
        <span className="hint">{STATUS_LABELS[op.status]}</span>
      </div>
      {op.action === 'update' && op.target && (
        <p className="hint">
          変更前: {op.target.summary}（{formatRange(op.target)}）
        </p>
      )}
      {op.action === 'delete' && op.target && (
        <p>
          {op.target.summary}（{formatRange(op.target)}）
        </p>
      )}
      {op.draft && <DraftDetails draft={op.draft} />}
      {op.status === 'pending' && (
        <>
          <p className="hint">内容を確認してください。「承認して実行」を押すまで Google カレンダーは変更されません。</p>
          <div className="actions">
            <button className="btn" disabled={busy} onClick={() => void decide(false)}>
              却下
            </button>
            <button className={`btn ${op.action === 'delete' ? 'danger' : 'primary'}`} disabled={busy} onClick={() => void decide(true)}>
              {busy ? '実行中…' : '承認して実行'}
            </button>
          </div>
        </>
      )}
      {op.status === 'failed' && op.error && <p className="error-text">{op.error}</p>}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
