import { useState } from 'react'
import { api, errorMessage } from '../api/client'

/** スマホの名前の候補（あとで PC の設定画面に表示して、どの端末か分かるようにする） */
function guessDeviceName(): string {
  const ua = navigator.userAgent
  if (/iPhone/.test(ua)) return 'iPhone'
  if (/iPad/.test(ua)) return 'iPad'
  if (/Android/.test(ua)) return 'Android'
  return 'スマホ'
}

/** スマホから初めて開いたとき: PC の画面に出ている6桁の合言葉を入れて、この端末をつなぐ */
export function PairPage({ onPaired }: { onPaired: () => void }) {
  const [pin, setPin] = useState('')
  const [name, setName] = useState(guessDeviceName)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setBusy(true)
    setError('')
    try {
      await api.pair(pin, name)
      onPaired()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="center-screen pair-page">
      <form
        className="panel pair-panel"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <img src="/icons/icon-192.png" alt="" width={72} height={72} />
        <h1>AnotherMe につなぐ</h1>
        <p className="hint">
          PC の AnotherMe で「設定」→「スマホから使う」→「スマホをつなぐ」を押すと、6桁の合言葉が表示されます。それを入れてください。
        </p>
        <label className="field">
          <span>合言葉（6桁）</span>
          <input
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            maxLength={6}
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
            className="pin-input"
            autoFocus
          />
        </label>
        <label className="field">
          <span>この端末の名前</span>
          <input type="text" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
        </label>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="btn primary" disabled={busy || pin.length !== 6}>
          つなぐ
        </button>
      </form>
    </div>
  )
}
