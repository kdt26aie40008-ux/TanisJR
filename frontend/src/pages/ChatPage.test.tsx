import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { jsonResponse, mockFetch, sseResponse } from '../test/fetchMock'
import { renderWithConversation } from '../test/render'
import { ChatPage } from './ChatPage'

const MODEL_OK = {
  ollama_available: true,
  message: null,
  installed: [{ name: 'qwen3:8b', size_gb: 5.2 }],
  configured_model: 'qwen3:8b',
  configured_model_installed: true,
  catalog: [{ name: 'qwen3:8b', size_gb: 5.2, description: '', recommended: true }],
  storage_path: 'C:\\Users\\x\\.ollama\\models',
  free_space_gb: 100,
}

describe('ChatPage', () => {
  it('streams the assistant reply', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      'GET /api/settings': () => jsonResponse({ save_conversations_default: false }),
      'GET /api/models/status': () => jsonResponse(MODEL_OK),
      'POST /api/chat': () =>
        sseResponse([
          { type: 'token', content: 'こんにち' },
          { type: 'token', content: 'は。' },
          { type: 'done', model: 'qwen3:8b' },
        ]),
    })
    renderWithConversation(<ChatPage aiName="タニス" />)
    await user.type(screen.getByLabelText('メッセージ'), 'やあ{Enter}')

    expect(await screen.findByText('こんにちは。')).toBeInTheDocument()
    const body = JSON.parse(String(calls.find((c) => c.url === '/api/chat')!.init!.body))
    expect(body).toEqual({ messages: [{ role: 'user', content: 'やあ' }] })
  })

  it('shows stream errors and restores the input', async () => {
    const user = userEvent.setup()
    mockFetch({
      'GET /api/models/status': () => jsonResponse(MODEL_OK),
      'POST /api/chat': () =>
        sseResponse([{ type: 'error', code: 'ollama_unavailable', message: 'Ollama に接続できません。' }]),
    })
    renderWithConversation(<ChatPage aiName="タニス" />)
    await user.type(screen.getByLabelText('メッセージ'), 'テスト{Enter}')

    expect(await screen.findByRole('alert')).toHaveTextContent('Ollama に接続できません。')
    expect(screen.getByLabelText('メッセージ')).toHaveValue('テスト')
  })

  it('offers download with size when the model is missing', async () => {
    const user = userEvent.setup()
    mockFetch({
      'GET /api/models/status': () => jsonResponse({ ...MODEL_OK, installed: [], configured_model_installed: false }),
    })
    renderWithConversation(<ChatPage aiName="タニス" />)
    await user.click(await screen.findByRole('button', { name: /ダウンロード（約5.2GB）/ }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('C:\\Users\\x\\.ollama\\models')).toBeInTheDocument()
    expect(within(dialog).getByText('約 5.2 GB')).toBeInTheDocument()
    // 確認ボタンを押すまでダウンロード要求は送らない
    expect(within(dialog).getByRole('button', { name: 'ダウンロードする' })).toBeInTheDocument()
  })
})
