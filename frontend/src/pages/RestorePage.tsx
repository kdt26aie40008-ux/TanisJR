import { useState } from 'react'
import { api, errorMessage } from '../api/client'
import { BackupRestore } from '../components/BackupPanel'

/**
 * 暗号鍵が読み込めない（別のPC・別の Windows ユーザー・Windows 再インストール後など）ときの画面。
 * データは消さず、バックアップからの復元か、「新しく始める」（データを退避して空の状態から始める）を選べる。
 */
export function RestorePage({ reason, onRestored }: { reason: string; onRestored: () => void }) {
  return (
    <div className="setup">
      <div className="setup-card panel">
        <header className="setup-header">
          <span className="brand-mark" aria-hidden>
            ◆
          </span>
          <h1>データがロックされています</h1>
        </header>
        <div className="banner warn" role="alert">
          {reason}
        </div>
        <p className="hint">
          保存データは暗号化されており、このPC・このWindowsユーザーの暗号鍵では読み込めない状態です。データは削除されていません。
        </p>
        <h2>自分のデータを戻す</h2>
        <p className="hint">以前に作成したバックアップファイルとパスフレーズで復元します。</p>
        <BackupRestore onRestored={onRestored} />
        <hr className="divider" />
        <StartFresh onDone={onRestored} />
      </div>
    </div>
  )
}

function StartFresh({ onDone }: { onDone: () => void }) {
  const [agreed, setAgreed] = useState(false)
  const [state, setState] = useState<'idle' | 'working' | 'restart-needed' | 'error'>('idle')
  const [error, setError] = useState('')

  const start = async () => {
    setState('working')
    setError('')
    try {
      const result = await api.startFresh()
      if (!result.restarting) {
        setState('restart-needed')
        return
      }
      // サーバーが再起動し、空のデータで立ち上がるのを待つ
      const started = Date.now()
      const poll = window.setInterval(async () => {
        try {
          const health = await api.health()
          if (!health.data_locked) {
            window.clearInterval(poll)
            onDone()
          }
        } catch {
          if (Date.now() - started > 90_000) {
            window.clearInterval(poll)
            setState('restart-needed')
          }
        }
      }, 1500)
    } catch (err) {
      setError(errorMessage(err))
      setState('error')
    }
  }

  return (
    <div>
      <h2>このPCで新しく始める</h2>
      <p className="hint">
        このPCを初めて使う人や、元のデータが不要な場合は、何もない状態から始められます。
        今のデータは削除せず、同じ場所に「data-archived-日時」という名前のフォルダーとして残します（このPCでは読めません）。
      </p>
      <label className="checkbox">
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        今のデータを使わずに、新しく始めることを理解しました
      </label>
      <div className="actions">
        <button className="btn primary" disabled={!agreed || state === 'working'} onClick={() => void start()}>
          {state === 'working' ? '準備しています…' : '新しく始める'}
        </button>
      </div>
      {state === 'restart-needed' && (
        <p className="warn-text" role="status">
          アプリを再起動すると、新しい状態で始まります（start.bat を実行し直してください）。
        </p>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
