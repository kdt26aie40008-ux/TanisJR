import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AppSettings, ProfileEntry } from '../api/types'
import { jsonResponse, mockFetch } from '../test/fetchMock'
import { WakeSettings } from './AssistantSettings'
import { SelfProfilePanel } from './SelfProfilePanel'

describe('WakeSettings', () => {
  it('cannot be turned on until "あなたのこと" is filled in', async () => {
    mockFetch({
      'GET /api/wake/status': () =>
        jsonResponse({ enabled: false, ready: false, missing: ['呼んでほしい名前', 'あなたの特徴（口ぐせ・話し方・生活のリズムなど）'] }),
    })
    render(<WakeSettings aiName="タニス" enabled={false} version="" onChange={vi.fn()} />)
    expect(await screen.findByText(/呼んでほしい名前、あなたの特徴/)).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: '「ねえ、タニス」と呼んだら起きる' })).toBeDisabled()
  })

  it('asks for consent before listening', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const calls = mockFetch({
      'GET /api/wake/status': () => jsonResponse({ enabled: false, ready: true, missing: [] }),
      'POST /api/wake': () => jsonResponse({ enabled: true, ready: true, missing: [] }),
    })
    render(<WakeSettings aiName="タニス" enabled={false} version="" onChange={onChange} />)
    const toggle = screen.getByRole('switch', { name: '「ねえ、タニス」と呼んだら起きる' })
    await vi.waitFor(() => expect(toggle).toBeEnabled())
    await user.click(toggle)
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/保存も外部への送信もしません/)).toBeInTheDocument()
    // 同意するまでは送らない
    expect(calls.some((c) => c.url === '/api/wake')).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: '同意してオンにする' }))
    const sent = calls.find((c) => c.url === '/api/wake')!
    expect(JSON.parse(String(sent.init!.body))).toEqual({ enabled: true, consent: true })
    expect(onChange).toHaveBeenCalledWith(true)
  })
})

describe('SelfProfilePanel', () => {
  it('starts personality from the first-time answer and saves each field', async () => {
    const user = userEvent.setup()
    const profile = [
      { key: 'setup.q2_personality', question: 'q2', content: '負けず嫌い', source: '', importance: 10, confirmation_status: '', created_at: '', updated_at: '' },
    ] as unknown as ProfileEntry[]
    const settings = { ai_name: 'タニス', wake_reading: '', language: 'ja' } as AppSettings
    const saveSettings = vi.fn(async () => true)
    const calls = mockFetch({
      'PUT /api/profile': (_url, init) => {
        const { key, content } = JSON.parse(String(init!.body))
        return jsonResponse({ key, content, question: '', source: 'user_edit', importance: 10, confirmation_status: 'confirmed', created_at: '', updated_at: 'now' })
      },
    })
    render(
      <SelfProfilePanel settings={settings} profile={profile} update={vi.fn()} saveSettings={saveSettings} onProfileSaved={vi.fn()} />,
    )
    expect(screen.getByLabelText('あなたの個性（性格・価値観・好き嫌い）')).toHaveValue('負けず嫌い')
    await user.type(screen.getByLabelText('呼んでほしい名前'), 'たろう')
    await user.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByText('保存しました。')).toBeInTheDocument()
    const saved = calls.filter((c) => c.url === '/api/profile').map((c) => JSON.parse(String(c.init!.body)).key)
    // 空欄の項目は送らない
    expect(saved).toEqual(['self.user_name', 'self.personality'])
    expect(saveSettings).toHaveBeenCalled()
  })

  it('warns that read-aloud is Japanese only', () => {
    const settings = { ai_name: 'タニス', wake_reading: '', language: 'en' } as AppSettings
    render(<SelfProfilePanel settings={settings} profile={[]} update={vi.fn()} saveSettings={vi.fn()} onProfileSaved={vi.fn()} />)
    expect(screen.getByText(/日本語以外では、声での返事/)).toBeInTheDocument()
  })
})
