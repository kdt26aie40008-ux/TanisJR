import { Trash2, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { AppSettings, BackgroundKind, CustomBackground, WeatherPlace } from '../api/types'

const KIND_LABELS: Record<BackgroundKind, string> = {
  home: 'おうち（雨の日・朝晩にいる場所）',
  indoor: 'おでかけ先（屋内）',
  outdoor: 'おでかけ先（屋外。時間帯で明るさが変わる）',
}

const BUILTIN: { value: string; label: string }[] = [
  { value: 'auto', label: '自動（時間帯と天気で、おうち・公園・街・カフェへ出かける）' },
  { value: 'room', label: 'いつもおうち' },
  { value: 'park', label: 'いつも公園' },
  { value: 'street', label: 'いつも街' },
  { value: 'cafe', label: 'いつもカフェ' },
]

interface Props {
  settings: AppSettings
  update: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void
  /** 場所の選択はすぐ保存されるので、画面の設定にも反映する */
  onPlaceSaved: (place: WeatherPlace, label: string) => void
}

/** 設定「背景と天気」: アバターのいる場所・天気予報・自分で用意した背景画像 */
export function SceneSettings({ settings, update, onPlaceSaved }: Props) {
  const [backgrounds, setBackgrounds] = useState<CustomBackground[]>([])
  const [query, setQuery] = useState('')
  const [places, setPlaces] = useState<WeatherPlace[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [newName, setNewName] = useState('')
  const [newKind, setNewKind] = useState<BackgroundKind>('indoor')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.backgrounds().then((r) => setBackgrounds(r.backgrounds), () => undefined)
  }, [])

  const search = async () => {
    if (!query.trim()) return
    setBusy(true)
    setMessage(null)
    try {
      const result = await api.searchWeatherPlaces(query.trim())
      setPlaces(result.places)
      if (result.places.length === 0) setMessage({ kind: 'error', text: '見つかりませんでした。市区町村名で探してみてください。' })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  const choose = async (place: WeatherPlace) => {
    try {
      const saved = await api.chooseWeatherPlace(place)
      onPlaceSaved(place, saved.place)
      setPlaces(null)
      setQuery('')
      setMessage({ kind: 'ok', text: `天気の場所を「${saved.place}」にしました。` })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  const upload = async (file: File) => {
    setBusy(true)
    setMessage(null)
    try {
      const bg = await api.uploadBackground(file, newName || file.name.replace(/\.[^.]+$/, ''), newKind)
      setBackgrounds((prev) => [...prev, bg])
      setNewName('')
      setMessage({ kind: 'ok', text: `背景「${bg.name}」を追加しました。` })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const changeKind = async (bg: CustomBackground, kind: BackgroundKind) => {
    try {
      const saved = await api.updateBackground(bg.id, { kind })
      setBackgrounds((prev) => prev.map((b) => (b.id === bg.id ? saved : b)))
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  const remove = async (bg: CustomBackground) => {
    if (!window.confirm(`背景「${bg.name}」を削除しますか？`)) return
    try {
      await api.deleteBackground(bg.id)
      setBackgrounds((prev) => prev.filter((b) => b.id !== bg.id))
      if (settings.scene_mode === `custom:${bg.id}`) update('scene_mode', 'auto')
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  return (
    <div className="scene-settings">
      <label className="field">
        <span>{settings.ai_name} のいる場所</span>
        <select value={settings.scene_mode} onChange={(e) => update('scene_mode', e.target.value)}>
          {BUILTIN.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
          {backgrounds.map((b) => (
            <option key={b.id} value={`custom:${b.id}`}>
              いつも「{b.name}」
            </option>
          ))}
        </select>
      </label>
      <p className="hint">
        自動にすると、夜・朝・雨や雪の日はおうちにいて、昼間は2時間ごとに公園・街・カフェなどへ出かけます。自分で追加した背景も行き先に入ります。
      </p>

      <h4>天気予報</h4>
      <label className={`switch${settings.weather_enabled ? ' on' : ''}`}>
        <input
          type="checkbox"
          role="switch"
          checked={settings.weather_enabled}
          onChange={(e) => update('weather_enabled', e.target.checked)}
        />
        <span className="switch-track" aria-hidden />
        天気予報を使う（雨の日はおうちにいる・外の景色に雨や雪を降らせる・天気を聞くと答える）
      </label>
      <p className="hint">
        天気は Open-Meteo（無料の天気予報サービス）から取得します。送るのは下で選んだ場所の緯度・経度だけで、会話や名前は送りません。30分に1回まで問い合わせます。
      </p>
      <p className="hint">いまの場所: {settings.weather_place || '（まだ選んでいません）'}</p>
      <div className="inline-form">
        <input
          type="text"
          value={query}
          maxLength={64}
          placeholder="市区町村名（例: 神戸）"
          aria-label="天気の場所を探す"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void search()
            }
          }}
        />
        <button type="button" className="btn small" onClick={() => void search()} disabled={busy || !query.trim()}>
          探す
        </button>
      </div>
      {places && places.length > 0 && (
        <ul className="place-list">
          {places.map((p) => (
            <li key={`${p.latitude},${p.longitude}`}>
              <button type="button" className="btn small ghost" onClick={() => void choose(p)}>
                {p.name}
                {p.detail && <span className="hint">（{p.detail}）</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      <h4>自分で用意した背景</h4>
      <p className="hint">
        写真やイラスト（PNG・JPEG・WebP、15MBまで）を背景に使えます。画像はこの PC の中にだけ保存されます。
      </p>
      <div className="inline-form">
        <input type="text" value={newName} maxLength={40} placeholder="名前（例: 海辺）" aria-label="背景の名前" onChange={(e) => setNewName(e.target.value)} />
        <select value={newKind} aria-label="背景の種類" onChange={(e) => setNewKind(e.target.value as BackgroundKind)}>
          {(Object.keys(KIND_LABELS) as BackgroundKind[]).map((k) => (
            <option key={k} value={k}>
              {KIND_LABELS[k]}
            </option>
          ))}
        </select>
        <button type="button" className="btn small" onClick={() => fileRef.current?.click()} disabled={busy}>
          <Upload size={14} aria-hidden />
          画像を選ぶ
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          hidden
          aria-label="背景の画像"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void upload(file)
          }}
        />
      </div>
      {backgrounds.length > 0 && (
        <ul className="background-list">
          {backgrounds.map((b) => (
            <li key={b.id}>
              <img src={api.backgroundFileUrl(b.id)} alt="" />
              <span className="background-name">{b.name}</span>
              <select value={b.kind} aria-label={`${b.name} の種類`} onChange={(e) => void changeKind(b, e.target.value as BackgroundKind)}>
                {(Object.keys(KIND_LABELS) as BackgroundKind[]).map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABELS[k]}
                  </option>
                ))}
              </select>
              <button type="button" className="btn small ghost" onClick={() => void remove(b)} aria-label={`${b.name} を削除`}>
                <Trash2 size={14} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      {message && (
        <p className={message.kind === 'ok' ? 'ok-text' : 'error-text'} role="status">
          {message.text}
        </p>
      )}
    </div>
  )
}
