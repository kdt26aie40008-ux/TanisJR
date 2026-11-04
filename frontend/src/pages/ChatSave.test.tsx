import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { jsonResponse, mockFetch, sseResponse } from '../test/fetchMock'
import { renderWithConversation } from '../test/render'
import { ChatPage } from './ChatPage'

const SETTINGS = { save_conversations_default: false }
const MODEL_OK = {
  ollama_available: true,
  message: null,
  installed: [],
  configured_model: 'qwen3:8b',
  configured_model_installed: true,
  embedding_model: 'qwen3-embedding:0.6b',
  embedding_model_installed: true,
  catalog: [],
  storage_path: '',
  free_space_gb: 1,
}
const CID = 'a'.repeat(32)

function routes(extra: Record<string, Parameters<typeof mockFetch>[0][string]> = {}) {
  return {
    'GET /api/settings': () => jsonResponse(SETTINGS),
    'GET /api/models/status': () => jsonResponse(MODEL_OK),
    'POST /api/conversations': () =>
      jsonResponse({ id: CID, title: 't', message_count: 0, created_at: '', updated_at: '' }),
    'POST /api/chat': () =>
      sseResponse([
        { type: 'memories_used', items: [{ id: 'm1', content: 'ユーザーはラーメンが好き', category: 'preference' }] },
        { type: 'token', content: '了解' },
        { type: 'saved', conversation_id: CID },
        { type: 'done', model: 'qwen3:8b' },
      ]),
    ...extra,
  }
}

describe('ChatPage saving', () => {
  it('does not save by default', async () => {
    const user = userEvent.setup()
    const calls = mockFetch(routes())
    renderWithConversation(<ChatPage aiName="タニス" />)
    expect(screen.getByTestId('save-status')).toHaveTextContent('この会話は保存されません')
    await user.type(screen.getByLabelText('メッセージ'), 'やあ{Enter}')
    await screen.findByText('了解')
    const chat = calls.find((c) => c.url === '/api/chat')!
    expect(JSON.parse(String(chat.init!.body))).not.toHaveProperty('conversation_id')
    expect(calls.some((c) => c.url === '/api/conversations')).toBe(false)
  })

  it('saves earlier messages when switched on mid-conversation', async () => {
    const user = userEvent.setup()
    const calls = mockFetch(routes())
    renderWithConversation(<ChatPage aiName="タニス" />)
    await user.type(screen.getByLabelText('メッセージ'), '一言目{Enter}')
    await screen.findByText('了解')

    await user.click(screen.getByRole('switch', { name: /この会話を保存/ }))
    expect(await screen.findByText('保存中')).toBeInTheDocument()
    const create = calls.find((c) => c.url === '/api/conversations')!
    expect(JSON.parse(String(create.init!.body))).toEqual({
      messages: [
        { role: 'user', content: '一言目' },
        { role: 'assistant', content: '了解' },
      ],
    })

    await user.type(screen.getByLabelText('メッセージ'), '二言目{Enter}')
    await screen.findAllByText('了解')
    const last = calls.filter((c) => c.url === '/api/chat').at(-1)!
    expect(JSON.parse(String(last.init!.body)).conversation_id).toBe(CID)
  })

  it('shows which memories were used', async () => {
    const user = userEvent.setup()
    mockFetch(routes())
    renderWithConversation(<ChatPage aiName="タニス" />)
    await user.type(screen.getByLabelText('メッセージ'), 'ラーメン{Enter}')
    expect(await screen.findByText('思い出したこと（1）')).toBeInTheDocument()
    expect(screen.getByText('ユーザーはラーメンが好き')).toBeInTheDocument()
  })

  it('shows calendar proposals as approval cards', async () => {
    const user = userEvent.setup()
    const op = {
      id: 'c'.repeat(32), action: 'create', event_id: null, target: null, source: 'ai', status: 'pending', error: null,
      result_event_id: null, created_at: '', decided_at: null,
      draft: { summary: '歯医者', all_day: false, start: '2026-11-03T10:00', end: '2026-11-03T11:00', location: '', description: '', reminder_minutes: null },
    }
    mockFetch(
      routes({
        'POST /api/chat': () =>
          sseResponse([
            { type: 'token', content: '内容を確認してね。' },
            { type: 'calendar_proposal', operation: op },
            { type: 'done', model: 'qwen3:8b' },
          ]),
      }),
    )
    renderWithConversation(<ChatPage aiName="タニス" />)
    await user.type(screen.getByLabelText('メッセージ'), '明日10時に歯医者入れて{Enter}')
    expect(await screen.findByText('会話からの提案')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '承認して実行' })).toBeInTheDocument()
  })

  it('switching off stops sending the conversation id', async () => {
    const user = userEvent.setup()
    const calls = mockFetch(routes({ 'GET /api/settings': () => jsonResponse({ save_conversations_default: true }) }))
    renderWithConversation(<ChatPage aiName="タニス" />)
    expect(await screen.findByText('次の送信から保存します')).toBeInTheDocument()
    await user.click(screen.getByRole('switch', { name: /この会話を保存/ }))
    await user.type(screen.getByLabelText('メッセージ'), 'x{Enter}')
    await screen.findByText('了解')
    const chat = calls.find((c) => c.url === '/api/chat')!
    expect(JSON.parse(String(chat.init!.body))).not.toHaveProperty('conversation_id')
  })
})
