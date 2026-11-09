import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { jsonResponse, mockFetch } from '../test/fetchMock'
import { RemotePanel } from './RemotePanel'

const READY = { installed: true, logged_in: true, dns_name: 'mypc.tail.ts.net', https_ready: true, serving: true }

describe('RemotePanel', () => {
  it('turns on remote use and shows a PIN with a QR code', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      'GET /api/remote/status': () => jsonResponse({ enabled: false, url: null, tailscale: READY, devices: [] }),
      'POST /api/remote/enable': () =>
        jsonResponse({ enabled: true, url: 'https://mypc.tail.ts.net', tailscale: READY, devices: [] }),
      'POST /api/remote/pairing': () =>
        jsonResponse({ pin: '123456', expires_at: Date.now() / 1000 + 600, url: 'https://mypc.tail.ts.net' }),
    })
    render(<RemotePanel />)
    await user.click(await screen.findByRole('switch', { name: 'スマホから使う' }))
    expect(await screen.findByText('https://mypc.tail.ts.net')).toBeInTheDocument()
    expect(calls.some((c) => c.url === '/api/remote/enable')).toBe(true)

    await user.click(screen.getByRole('button', { name: /スマホをつなぐ/ }))
    expect(await screen.findByLabelText('合言葉')).toHaveTextContent('123 456')
    expect(screen.getByAltText(/QR コード/).getAttribute('src')).toMatch(/^data:image\/png/)
  })

  it('cannot be turned on until Tailscale is ready', async () => {
    mockFetch({
      'GET /api/remote/status': () =>
        jsonResponse({ enabled: false, url: null, tailscale: { ...READY, https_ready: false }, devices: [] }),
    })
    render(<RemotePanel />)
    expect(await screen.findByRole('switch', { name: 'スマホから使う' })).toBeDisabled()
    expect(screen.getByText(/Enable HTTPS/)).toBeInTheDocument()
  })

  it('tells the phone that only the PC can change it', async () => {
    mockFetch({
      'GET /api/remote/status': () =>
        jsonResponse({ detail: { code: 'local_only', message: 'この操作は PC 本体からだけできます。' } }, 403),
    })
    render(<RemotePanel />)
    expect(await screen.findByText(/PC 本体の AnotherMe でだけ変更できます/)).toBeInTheDocument()
  })
})

describe('pairing from a phone', () => {
  it('asks for the PIN, then opens the app', async () => {
    const user = userEvent.setup()
    let paired = false
    const pairingRequired = () =>
      jsonResponse({ detail: { code: 'pairing_required', message: 'このスマホはまだつながっていません。' } }, 401)
    const calls = mockFetch({
      'GET /api/health': () => jsonResponse({ status: 'ok', data_locked: false }),
      // つないだあとは、合言葉の画面ではなく、いつもの読み込みに進む（ここでは読み込みの失敗で確かめる）
      'GET /api/setup/status': () =>
        paired ? jsonResponse({ detail: { code: 'x', message: '読み込みを再開しました' } }, 500) : pairingRequired(),
      'GET /api/settings': () => (paired ? jsonResponse({ ai_name: '' }) : pairingRequired()),
      'POST /api/remote/pair': () => {
        paired = true
        return jsonResponse({ paired: true })
      },
    })
    render(<App />)
    await user.type(await screen.findByLabelText('合言葉（6桁）'), '12ab3456')
    await user.click(screen.getByRole('button', { name: 'つなぐ' }))
    const sent = JSON.parse(String(calls.find((c) => c.url === '/api/remote/pair')!.init!.body))
    expect(sent.pin).toBe('123456')
    expect(await screen.findByText('読み込みを再開しました')).toBeInTheDocument()
    expect(screen.queryByLabelText('合言葉（6桁）')).toBeNull()
  })
})
