import { Smartphone, Trash2 } from 'lucide-react'
import QRCode from 'qrcode'
import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, errorMessage } from '../api/client'
import type { RemoteStatus } from '../api/types'

/** 設定「スマホから使う」: Tailscale 経由で、自分のスマホからこの PC の AnotherMe を使う */
export function RemotePanel() {
  const [status, setStatus] = useState<RemoteStatus | null>(null)
  const [localOnly, setLocalOnly] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [pairing, setPairing] = useState<{ pin: string; expires_at: number; url: string; qr: string } | null>(null)

  const load = useCallback(() => {
    api.remoteStatus().then(setStatus, (err) => {
      // スマホから開いているときは、ここでは変更できない
      if (err instanceof ApiError && err.code === 'local_only') setLocalOnly(true)
      else setError(errorMessage(err))
    })
  }, [])
  useEffect(load, [load])

  // 合言葉の期限が切れたら消す
  useEffect(() => {
    if (!pairing) return
    const id = window.setTimeout(() => setPairing(null), Math.max(0, pairing.expires_at * 1000 - Date.now()))
    return () => window.clearTimeout(id)
  }, [pairing])

  const run = async (action: () => Promise<RemoteStatus>) => {
    setBusy(true)
    setError('')
    try {
      setStatus(await action())
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const startPairing = async () => {
    setError('')
    try {
      const p = await api.startPairing()
      const qr = await QRCode.toDataURL(p.url, { margin: 1, width: 220 })
      setPairing({ ...p, qr })
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const remove = async (id: string, name: string) => {
    if (!window.confirm(`「${name}」のつながりを解除しますか？ この端末からは使えなくなります。`)) return
    try {
      await api.removeDevice(id)
      load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  if (localOnly) {
    return <p className="hint">スマホから使う設定は、PC 本体の AnotherMe でだけ変更できます。</p>
  }
  if (!status) return <p className="hint">{error || '確認しています…'}</p>
  const ts = status.tailscale

  return (
    <div className="remote-panel">
      <p className="hint">
        自分の PC とスマホだけをつなぐ Tailscale を使って、外出先からもスマホで話せます。インターネットには公開しません。
        スマホは、この画面で表示する合言葉を入れた端末だけが使えます。PC の電源が入っていて、AnotherMe が動いている必要があります。
      </p>
      <ul className="check-list">
        <li className={ts.installed ? 'ok-text' : 'warn-text'}>
          {ts.installed ? '✓ Tailscale が入っています' : '✕ Tailscale が入っていません（https://tailscale.com/download）'}
        </li>
        <li className={ts.logged_in ? 'ok-text' : 'warn-text'}>
          {ts.logged_in ? `✓ ログイン済み（${ts.dns_name}）` : '✕ Tailscale にログインしていません'}
        </li>
        <li className={ts.https_ready ? 'ok-text' : 'warn-text'}>
          {ts.https_ready ? '✓ HTTPS が使えます' : '✕ 管理画面の DNS ページで「Enable HTTPS」を押してください'}
        </li>
      </ul>

      <label className={`switch${status.enabled ? ' on' : ''}`}>
        <input
          type="checkbox"
          role="switch"
          checked={status.enabled}
          disabled={busy || (!status.enabled && !(ts.installed && ts.logged_in && ts.https_ready))}
          onChange={(e) => void run(e.target.checked ? api.enableRemote : api.disableRemote)}
        />
        <span className="switch-track" aria-hidden />
        スマホから使う
      </label>

      {status.enabled && status.url && (
        <>
          <p>
            スマホで開くアドレス: <code>{status.url}</code>
          </p>
          {!ts.serving && <p className="warn-text">Tailscale の中継が止まっています。オフにしてからオンにし直してください。</p>}
          <button type="button" className="btn small primary" onClick={() => void startPairing()}>
            <Smartphone size={14} aria-hidden />
            スマホをつなぐ
          </button>
          {pairing && (
            <div className="pairing-box" role="status">
              <img src={pairing.qr} alt={`${pairing.url} の QR コード`} width={180} height={180} />
              <div>
                <p className="hint">① スマホのカメラで QR コードを読むか、上のアドレスを開く</p>
                <p className="hint">② スマホに出た画面に、この合言葉を入れる（10分間・1回だけ有効）</p>
                <p className="pin-display" aria-label="合言葉">
                  {pairing.pin.slice(0, 3)} {pairing.pin.slice(3)}
                </p>
              </div>
            </div>
          )}
        </>
      )}

      {status.devices.length > 0 && (
        <>
          <h4>つないだ端末</h4>
          <ul className="device-list">
            {status.devices.map((d) => (
              <li key={d.id}>
                <span>{d.name}</span>
                <span className="hint">
                  {new Date(d.created_at).toLocaleDateString('ja-JP')} に登録
                  {d.last_seen && ` ・ 最後に使った日 ${new Date(d.last_seen).toLocaleDateString('ja-JP')}`}
                </span>
                <button type="button" className="btn small ghost" onClick={() => void remove(d.id, d.name)} aria-label={`${d.name} のつながりを解除`}>
                  <Trash2 size={14} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
