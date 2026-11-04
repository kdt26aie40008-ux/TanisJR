import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { AppSettings, WakeStatus } from '../api/types'

interface ProactiveProps {
  settings: AppSettings
  update: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void
}

/** 設定「自分から話しかける」（アプリを開いている間だけ） */
export function ProactiveSettings({ settings, update }: ProactiveProps) {
  const on = settings.proactive_enabled
  return (
    <div className="behavior-group">
      <label className={`switch${on ? ' on' : ''}`}>
        <input
          type="checkbox"
          role="switch"
          checked={on}
          onChange={(e) => update('proactive_enabled', e.target.checked)}
        />
        <span className="switch-track" aria-hidden />
        <span className="behavior-label">{settings.ai_name} から話しかける</span>
      </label>
      <p className="hint">
        アプリを開いている間、朝のあいさつや予定の前の声かけをします。アプリを閉じているときは、予定の通知だけが Windows
        の通知で届きます。
      </p>
      {on && (
        <div className="sub-settings">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={settings.proactive_morning}
              onChange={(e) => update('proactive_morning', e.target.checked)}
            />
            朝、その日はじめて開いたときにあいさつする（11時まで）
          </label>
          <label className="field inline">
            <span>予定の前に声をかける</span>
            <select
              value={settings.proactive_event_minutes}
              onChange={(e) => update('proactive_event_minutes', Number(e.target.value))}
            >
              <option value={0}>声をかけない</option>
              {[5, 10, 15, 30, 60].map((m) => (
                <option key={m} value={m}>
                  {m}分前
                </option>
              ))}
            </select>
          </label>
          <label className="field inline">
            <span>しばらく話していないときに声をかける</span>
            <select
              value={settings.proactive_idle_hours}
              onChange={(e) => update('proactive_idle_hours', Number(e.target.value))}
            >
              <option value={0}>声をかけない</option>
              {[1, 2, 3, 6].map((h) => (
                <option key={h} value={h}>
                  {h}時間たったら
                </option>
              ))}
            </select>
          </label>
          <div className="field inline">
            <span>話しかけない時間</span>
            <span className="time-range">
              <input
                type="time"
                aria-label="話しかけない時間の開始"
                value={settings.quiet_start}
                onChange={(e) => update('quiet_start', e.target.value)}
              />
              〜
              <input
                type="time"
                aria-label="話しかけない時間の終了"
                value={settings.quiet_end}
                onChange={(e) => update('quiet_end', e.target.value)}
              />
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

interface WakeProps {
  aiName: string
  enabled: boolean
  /** 「あなたのこと」が変わったら入力状況を確認し直すための値 */
  version: string
  onChange: (enabled: boolean) => void
}

/**
 * 設定「ねえ○○で起きる」。マイクを常に聞くため、専用の操作でのみオンにする。
 * 「あなたのこと」をすべて入力し、同意した場合だけ使える。
 */
export function WakeSettings({ aiName, enabled, version, onChange }: WakeProps) {
  const [status, setStatus] = useState<WakeStatus | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.wakeStatus().then(setStatus, (err) => setError(errorMessage(err)))
  }, [version, enabled])

  const apply = async (value: boolean, consent = false) => {
    setError('')
    try {
      const next = await api.setWake(value, consent)
      setStatus(next)
      onChange(next.enabled)
      setConfirming(false)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const ready = status?.ready ?? false
  return (
    <div className="behavior-group">
      <label className={`switch${enabled ? ' on' : ''}`}>
        <input
          type="checkbox"
          role="switch"
          checked={enabled}
          disabled={!ready && !enabled}
          onChange={(e) => (e.target.checked ? setConfirming(true) : void apply(false))}
        />
        <span className="switch-track" aria-hidden />
        <span className="behavior-label">「ねえ、{aiName}」と呼んだら起きる</span>
      </label>
      {status && !ready && (
        <p className="warn-text">
          使うには、先に上の「あなたのこと」で次の項目を入力して保存してください: {status.missing.join('、')}
        </p>
      )}
      <p className="hint">
        アプリを開いている間、マイクで呼びかけを待ちます。聞いた音はこの PC の中で文字にして名前を探すだけで、保存も送信もしません。
        聞いている間は画面に「呼ばれるのを待っています」と表示します。
      </p>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {confirming && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="wake-title">
          <div className="dialog panel">
            <h2 id="wake-title">マイクで呼びかけを待ちます</h2>
            <ul>
              <li>アプリを開いている間は、話しかけていなくてもマイクの音を聞き続けます。</li>
              <li>聞いた音はこの PC の中で文字にして「{aiName}」の名前を探すだけで、保存も外部への送信もしません。</li>
              <li>聞いている間は、画面に「呼ばれるのを待っています」と表示します。設定でいつでもオフにできます。</li>
              <li>声を文字にするため、CPU を使い続けます。PC の動作が重くなることがあります。</li>
            </ul>
            <div className="actions">
              <button className="btn" onClick={() => setConfirming(false)}>
                やめる
              </button>
              <button className="btn primary" onClick={() => void apply(true, true)}>
                同意してオンにする
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
