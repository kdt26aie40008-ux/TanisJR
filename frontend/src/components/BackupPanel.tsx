import { useState } from 'react'
import { api, ApiError, errorMessage } from '../api/client'

const MIN_PASSPHRASE = 10

type Feedback = { kind: 'ok' | 'error'; text: string } | null

function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).replace(/^data:.*?;base64,/, ''))
    reader.onerror = () => reject(new Error('ファイルを読み込めませんでした。'))
    reader.readAsDataURL(file)
  })
}

/** 暗号化バックアップの作成（ダウンロード）。 */
export function BackupCreate() {
  const [passphrase, setPassphrase] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const tooShort = passphrase.length < MIN_PASSPHRASE
  const mismatch = confirm.length > 0 && passphrase !== confirm

  const create = async () => {
    setBusy(true)
    setFeedback(null)
    try {
      const { blob, filename } = await api.createBackup(passphrase)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      setPassphrase('')
      setConfirm('')
      setFeedback({ kind: 'ok', text: `バックアップ「${filename}」を作成しました。安全な場所に保管してください。` })
    } catch (err) {
      setFeedback({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h3>バックアップを作成</h3>
      <p className="hint">
        プロフィール・記憶・保存した会話・設定を、パスフレーズで暗号化して1つのファイルに保存します。
        パスフレーズを忘れると復元できません。
      </p>
      <label className="field">
        <span>パスフレーズ（{MIN_PASSPHRASE}文字以上）</span>
        <input type="password" autoComplete="new-password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} />
      </label>
      <label className="field">
        <span>パスフレーズ（確認）</span>
        <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </label>
      {mismatch && <p className="error-text">パスフレーズが一致しません。</p>}
      <div className="actions">
        <button className="btn primary" disabled={busy || tooShort || passphrase !== confirm} onClick={() => void create()}>
          {busy ? '作成中…' : 'バックアップをダウンロード'}
        </button>
      </div>
      {feedback && (
        <p className={feedback.kind === 'ok' ? 'ok-text' : 'error-text'} role={feedback.kind === 'error' ? 'alert' : 'status'}>
          {feedback.text}
        </p>
      )}
    </div>
  )
}

/** バックアップファイルからの復元。現在のデータはすべて置き換えられる。 */
export function BackupRestore({ onRestored }: { onRestored: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [passphrase, setPassphrase] = useState('')
  const [agreed, setAgreed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>(null)

  const restore = async () => {
    if (!file) return
    setBusy(true)
    setFeedback(null)
    try {
      const result = await api.restoreBackup(passphrase, await readAsBase64(file))
      setFeedback({ kind: 'ok', text: `復元しました（バックアップ作成日時: ${new Date(result.backup_created_at).toLocaleString('ja-JP')}）。` })
      setPassphrase('')
      onRestored()
    } catch (err) {
      // ファイル読み込みの失敗は日本語メッセージ付きの Error、それ以外は API のエラー
      setFeedback({ kind: 'error', text: err instanceof ApiError || !(err instanceof Error) ? errorMessage(err) : err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h3>バックアップから復元</h3>
      <label className="field">
        <span>バックアップファイル（.twinbak）</span>
        <input type="file" accept=".twinbak" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        <span>パスフレーズ</span>
        <input type="password" autoComplete="off" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} />
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        現在のデータがすべてバックアップの内容に置き換わることを理解しました
      </label>
      <div className="actions">
        <button className="btn danger" disabled={busy || !file || !passphrase || !agreed} onClick={() => void restore()}>
          {busy ? '復元中…' : '復元する'}
        </button>
      </div>
      {feedback && (
        <p className={feedback.kind === 'ok' ? 'ok-text' : 'error-text'} role={feedback.kind === 'error' ? 'alert' : 'status'}>
          {feedback.text}
        </p>
      )}
    </div>
  )
}
