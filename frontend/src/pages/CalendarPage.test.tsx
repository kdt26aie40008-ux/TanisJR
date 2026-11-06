import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { jsonResponse, mockFetch } from '../test/fetchMock'
import { CalendarPage } from './CalendarPage'

// Google カレンダー連携のテストで使う状態（既定はアプリ内カレンダー）
const BASE_STATUS = { backend: 'google', configured: false, source: null, connected: false, client_id_hint: null, redirect_uri: 'http://127.0.0.1:8765/api/calendar/auth/callback', last_sync_at: null, last_error: null }
const SETTINGS = { notifications_enabled: true, default_reminder_minutes: 10, calendar_ai_proposals: true }
const SYSTEM = { pid: 1, uptime_seconds: 60, background: false, autostart: false, notifications_enabled: true }

function routes(status: object, extra: Parameters<typeof mockFetch>[0] = {}) {
  return {
    'GET /api/calendar/status': () => jsonResponse(status),
    'GET /api/settings': () => jsonResponse(SETTINGS),
    'GET /api/system/status': () => jsonResponse(SYSTEM),
    ...extra,
  }
}

describe('CalendarPage', () => {
  it('guides the OAuth client setup and states that notifications need the PC running', async () => {
    mockFetch(routes(BASE_STATUS))
    render(<CalendarPage />)
    expect(await screen.findByText(/Google Calendar API/)).toBeInTheDocument()
    expect(screen.getByText(/シャットダウン・スリープ中の予定は通知できません/)).toBeInTheDocument()
  })

  it('creates a pending operation from the form instead of changing the calendar directly', async () => {
    const user = userEvent.setup()
    const op = {
      id: 'b'.repeat(32), action: 'create', event_id: null, target: null, source: 'user', status: 'pending', error: null,
      result_event_id: null, created_at: '', decided_at: null,
      draft: { summary: '勉強会', all_day: false, start: '2026-11-03T14:00', end: '2026-11-03T15:00', location: '', description: '', reminder_minutes: null },
    }
    const calls = mockFetch(
      routes({ ...BASE_STATUS, configured: true, connected: true }, {
        'GET /api/calendar/events?days=14': () => jsonResponse([]),
        'GET /api/calendar/operations?status=pending': () => jsonResponse([]),
        'POST /api/calendar/operations': () => jsonResponse(op),
      }),
    )
    render(<CalendarPage />)
    await user.click(await screen.findByRole('button', { name: '予定を追加' }))
    await user.type(screen.getByLabelText('タイトル'), '勉強会')
    await user.click(screen.getByRole('button', { name: '確認へ進む' }))
    expect(await screen.findByRole('button', { name: '承認して実行' })).toBeInTheDocument()
    const post = calls.find((c) => c.url === '/api/calendar/operations')!
    expect(JSON.parse(String(post.init!.body)).action).toBe('create')
    expect(calls.some((c) => c.url.includes('/approve'))).toBe(false)
  })

  it('only asks to log in when the app ships a Google registration', async () => {
    const user = userEvent.setup()
    const opened: string[] = []
    window.open = ((url: string) => {
      opened.push(url)
      return null
    }) as typeof window.open
    mockFetch(
      routes({ ...BASE_STATUS, configured: true, source: 'bundled' }, {
        'POST /api/calendar/auth/start': () => jsonResponse({ url: 'https://accounts.google.com/o/oauth2/v2/auth?x=1' }),
      }),
    )
    render(<CalendarPage />)
    await user.click(await screen.findByRole('button', { name: 'Google でログインして連携' }))
    expect(opened).toEqual(['https://accounts.google.com/o/oauth2/v2/auth?x=1'])
    // JSON ファイルの登録は求めない
    expect(screen.queryByLabelText('OAuth クライアントの JSON ファイル')).toBeNull()
  })

  it('uses the in-app calendar by default and saves the user own events right away', async () => {
    const user = userEvent.setup()
    const day = new Date()
    const iso = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
    let saved = false
    const done = {
      id: 'c'.repeat(32), action: 'create', event_id: null, target: null, source: 'user', status: 'done', error: null,
      result_event_id: 'e'.repeat(32), created_at: '', decided_at: '',
      draft: { summary: '勉強会', all_day: false, start: `${iso}T14:00`, end: `${iso}T15:00`, location: '', description: '', reminder_minutes: null },
    }
    const event = { id: 'e'.repeat(32), summary: '勉強会', all_day: false, start: `${iso}T14:00:00+09:00`, end: `${iso}T15:00:00+09:00`, location: '', description: '', html_link: '', notify_minutes: null }
    const calls = mockFetch({
      ...routes({ ...BASE_STATUS, backend: 'local' }),
      'GET /api/calendar/operations?status=pending': () => jsonResponse([]),
      'POST /api/calendar/operations': () => {
        saved = true
        return jsonResponse(done)
      },
      // 予定の取得は、保存の前後で結果を変える（URL は表示する月で変わる）
      'GET /api/calendar/events*': () => jsonResponse(saved ? [event] : []),
    })

    render(<CalendarPage />)
    // Google の連携画面ではなく、月のカレンダーが出る
    expect(await screen.findByRole('grid', { name: '月のカレンダー' })).toBeInTheDocument()
    expect(screen.queryByText('Google でログインして連携')).toBeNull()
    expect(screen.getByText(/ほかの人と共有・公開する機能はありません/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'この日に予定を追加' }))
    await user.type(screen.getByLabelText('タイトル'), '勉強会')
    await user.click(screen.getByRole('button', { name: '保存' }))
    // 承認待ちにはならず、すぐ月の表示と一覧に出る
    expect((await screen.findAllByText(/勉強会/)).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: '承認して実行' })).toBeNull()
    const post = calls.find((c) => c.url === '/api/calendar/operations')!
    expect(JSON.parse(String(post.init!.body)).draft.start.startsWith(iso)).toBe(true)
  })

  it('shows the autostart switch', async () => {
    mockFetch(routes(BASE_STATUS))
    render(<CalendarPage />)
    expect(await screen.findByLabelText('Windows のサインイン時に自動で起動する')).not.toBeChecked()
  })
})
