import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { Avatar } from '../api/types'
import { AvatarStage } from '../components/avatar/AvatarStage'
import type { Activity } from '../components/avatar/AvatarViewer'
import type { Emotion } from '../lib/emotion'
import { formatDate } from '../lib/labels'
import { useAvatars } from '../state/useActiveAvatar'

const EMOTION_BUTTONS: [Emotion, string][] = [
  ['neutral', '通常'],
  ['happy', '喜び'],
  ['sad', '悲しみ'],
  ['surprised', '驚き'],
  ['relaxed', '穏やか'],
  ['angry', '怒り'],
]

const PERMISSION_LABELS: Record<string, string> = {
  onlyAuthor: '作者のみ',
  onlySeparatelyLicensedPerson: '許可された人のみ',
  everyone: '誰でも',
  OnlyAuthor: '作者のみ',
  ExplicitlyLicensedPerson: '許可された人のみ',
  Everyone: '誰でも',
}

const COMMERCIAL_LABELS: Record<string, string> = {
  personalNonProfit: '個人の非営利のみ',
  personalProfit: '個人の営利まで',
  corporation: '法人の商用も可',
  Disallow: '不可',
  Allow: '可',
}

function formatSize(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function AvatarPage() {
  const { avatars, active, error: loadError, reload } = useAvatars()
  const [error, setError] = useState('')
  const [emotion, setEmotion] = useState<Emotion>('neutral')
  const [activity, setActivity] = useState<Activity>('idle')
  const testUntil = useRef(0)

  // 口パクの確認用（2秒間、擬似的な音量を与える）
  const testLevel = () => {
    const now = performance.now()
    if (now > testUntil.current) return 0
    return 0.5 + 0.5 * Math.sin(now / 70)
  }

  useEffect(() => {
    if (activity !== 'speaking') return
    const id = window.setTimeout(() => setActivity('idle'), 2000)
    return () => window.clearTimeout(id)
  }, [activity])

  const run = async (fn: () => Promise<unknown>) => {
    setError('')
    try {
      await fn()
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <section className="page avatar-page">
      <h1>すがた</h1>
      {(error || loadError) && (
        <div className="banner error" role="alert">
          {error || loadError}
        </div>
      )}

      <div className="panel">
        <h2>表示確認</h2>
        <AvatarStage
          avatar={active}
          getLevel={testLevel}
          emotion={emotion}
          activity={activity}
          emptyMessage="アバターが選択されていません。下の一覧の標準アバターを「使用する」か、VRM ファイルを読み込んでください。"
        />
        {active && (
          <div className="actions wrap">
            {EMOTION_BUTTONS.map(([value, label]) => (
              <button
                key={value}
                className={`btn small${emotion === value ? ' primary' : ''}`}
                onClick={() => setEmotion(value)}
              >
                {label}
              </button>
            ))}
            <button
              className="btn small"
              onClick={() => {
                testUntil.current = performance.now() + 2000
                setActivity('speaking')
              }}
            >
              口パク確認
            </button>
            <button className="btn small" onClick={() => setActivity(activity === 'thinking' ? 'idle' : 'thinking')}>
              考え中
            </button>
          </div>
        )}
      </div>

      <UploadForm onUploaded={() => void reload()} onError={setError} />

      <div className="panel">
        <h2>登録済みのアバター</h2>
        {avatars === null ? (
          <p>読み込み中…</p>
        ) : avatars.length === 0 ? (
          <p className="empty">まだアバターがありません。</p>
        ) : (
          <ul className="memory-list">
            {avatars.map((a) => (
              <AvatarItem
                key={a.id}
                avatar={a}
                active={a.id === active?.id}
                onActivate={() => run(() => api.activateAvatar(a.id))}
                onTogglePlaceholder={() => run(() => api.updateAvatar(a.id, { is_placeholder: !a.is_placeholder }))}
                onRename={(name) => run(() => api.updateAvatar(a.id, { name }))}
                onDelete={() => {
                  if (window.confirm(`「${a.name}」を削除しますか？`)) void run(() => api.deleteAvatar(a.id))
                }}
              />
            ))}
          </ul>
        )}
      </div>

      <div className="panel">
        <h2>オリジナルのアバターを作るには</h2>
        <ol className="guide">
          <li>
            <a href="https://vroid.com/studio" target="_blank" rel="noopener noreferrer">
              VRoid Studio
            </a>
            （無料）などでモデルを作成します。
          </li>
          <li>「VRM 1.0」形式でエクスポートします。ライセンス設定（利用許可・商用利用・クレジット表記）も入力します。</li>
          <li>このページで読み込み、「仮モデル」のチェックを外すと正式なモデルとして扱われます。</li>
        </ol>
        <p className="hint">
          表情（喜び・悲しみ・驚き・穏やか・怒り）、まばたき（blink）、口の形（aa）が設定されたモデルで、表情と口パクが動作します。
          他人が作ったモデルは、その利用規約で許可されている範囲でのみ使用してください。
        </p>
      </div>
    </section>
  )
}

function UploadForm({ onUploaded, onError }: { onUploaded: () => void; onError: (m: string) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [placeholder, setPlaceholder] = useState(true)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const upload = async () => {
    if (!file) return
    setBusy(true)
    setDone('')
    onError('')
    try {
      const avatar = await api.uploadAvatar(file, name, placeholder)
      setDone(`「${avatar.name}」を登録しました。`)
      setFile(null)
      setName('')
      if (inputRef.current) inputRef.current.value = ''
      onUploaded()
    } catch (err) {
      onError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <h2>VRM ファイルを読み込む</h2>
      <label className="field">
        <span>VRM ファイル（.vrm、100MBまで）</span>
        <input ref={inputRef} type="file" accept=".vrm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        <span>表示名（省略するとモデル内の名前）</span>
        <input value={name} maxLength={64} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={placeholder} onChange={(e) => setPlaceholder(e.target.checked)} />
        仮モデルとして登録する（正式なモデルが用意できるまでの代用）
      </label>
      <div className="actions">
        <button className="btn primary" disabled={!file || busy} onClick={() => void upload()}>
          {busy ? '読み込み中…' : '登録する'}
        </button>
      </div>
      {done && (
        <p className="ok-text" role="status">
          {done}
        </p>
      )}
    </div>
  )
}

interface ItemProps {
  avatar: Avatar
  active: boolean
  onActivate: () => void
  onTogglePlaceholder: () => void
  onRename: (name: string) => void
  onDelete: () => void
}

function AvatarItem({ avatar, active, onActivate, onTogglePlaceholder, onRename, onDelete }: ItemProps) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(avatar.name)
  const m = avatar.meta
  return (
    <li className={`memory-item panel${active ? ' selected' : ''}`}>
      <div className="memory-head">
        {editing ? (
          <input value={name} maxLength={64} onChange={(e) => setName(e.target.value)} aria-label="表示名" />
        ) : (
          <strong>{avatar.name}</strong>
        )}
        {active && <span className="tag">使用中</span>}
        {avatar.builtin && <span className="tag">標準</span>}
        {avatar.is_placeholder && <span className="tag important">仮モデル</span>}
        <span className="hint">
          VRM {avatar.vrm_version} ・ {formatSize(avatar.size)}
          {avatar.builtin ? ' ・ アプリに同梱（ダウンロード不要）' : ` ・ ${formatDate(avatar.created_at)}`}
        </span>
      </div>
      <details className="memory-source">
        <summary>ライセンス情報</summary>
        <dl className="summary compact">
          <div>
            <dt>作者</dt>
            <dd>{m.authors || '（記載なし）'}</dd>
          </div>
          {m.copyright && (
            <div>
              <dt>著作権</dt>
              <dd>{m.copyright}</dd>
            </div>
          )}
          <div>
            <dt>利用できる人</dt>
            <dd>{PERMISSION_LABELS[m.avatar_permission] ?? (m.avatar_permission || '（記載なし）')}</dd>
          </div>
          <div>
            <dt>商用利用</dt>
            <dd>{COMMERCIAL_LABELS[m.commercial_usage] ?? (m.commercial_usage || '（記載なし）')}</dd>
          </div>
          <div>
            <dt>クレジット表記</dt>
            <dd>{m.credit_required ? '必要（画面に作者名を表示します）' : '不要'}</dd>
          </div>
          <div>
            <dt>再配布</dt>
            <dd>{m.allow_redistribution ? '可' : '不可'}</dd>
          </div>
          {m.license_name && (
            <div>
              <dt>ライセンス</dt>
              <dd>{m.license_name}</dd>
            </div>
          )}
          {m.license_url && (
            <div>
              <dt>規約</dt>
              <dd className="path">
                {/^https?:\/\//.test(m.license_url) ? (
                  <a href={m.license_url} target="_blank" rel="noopener noreferrer">
                    {m.license_url}
                  </a>
                ) : (
                  m.license_url
                )}
              </dd>
            </div>
          )}
        </dl>
      </details>
      <div className="actions">
        {editing ? (
          <>
            <button className="btn small" onClick={() => setEditing(false)}>
              キャンセル
            </button>
            <button
              className="btn small primary"
              onClick={() => {
                onRename(name)
                setEditing(false)
              }}
            >
              保存
            </button>
          </>
        ) : (
          <>
            {!active && (
              <button className="btn small primary" onClick={onActivate}>
                使用する
              </button>
            )}
            {!avatar.builtin && (
              <>
                <button className="btn small" onClick={onTogglePlaceholder}>
              {avatar.is_placeholder ? '正式なモデルにする' : '仮モデルにする'}
            </button>
            <button className="btn small" onClick={() => setEditing(true)}>
              名前を変更
            </button>
                <button className="btn small danger" onClick={onDelete}>
                  削除
                </button>
              </>
            )}
          </>
        )}
      </div>
    </li>
  )
}
