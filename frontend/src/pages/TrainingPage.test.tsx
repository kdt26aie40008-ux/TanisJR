import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { jsonResponse, mockFetch } from '../test/fetchMock'
import { TrainingPage } from './TrainingPage'

const EXAMPLE = {
  id: 'e'.repeat(32), source: 'conversation', conversation_id: null, user_text: '疲れた', assistant_text: '少し休もう',
  status: 'pending', created_at: '', updated_at: '', warnings: ['電話番号が含まれている可能性があります'],
}
const ENV = {
  training_python: true, converter: true, min_examples: 5, approved_examples: 8, running: null,
  bases: [{ id: 'qwen3-1.7b', label: 'Qwen3 1.7B', hf_repo: 'Qwen/Qwen3-1.7B', ollama_model: 'qwen3:1.7b', quantize_4bit: false, size_gb: 4.1, note: '', downloaded: true }],
}

function routes(extra: Parameters<typeof mockFetch>[0] = {}) {
  return {
    'GET /api/training/examples?status=pending': () => jsonResponse({ examples: [EXAMPLE], counts: { pending: 1, approved: 8, rejected: 0 } }),
    'GET /api/conversations': () => jsonResponse([]),
    'GET /api/training/environment': () => jsonResponse(ENV),
    'GET /api/training/runs': () => jsonResponse({ runs: [], model: 'qwen3:8b' }),
    ...extra,
  }
}

describe('TrainingPage', () => {
  it('lists pending examples with quality warnings and approves them', async () => {
    const user = userEvent.setup()
    const calls = mockFetch(routes({ [`POST /api/training/examples/${EXAMPLE.id}/approve`]: () => jsonResponse({ ...EXAMPLE, status: 'approved' }) }))
    render(<TrainingPage />)
    expect(await screen.findByText(/電話番号が含まれている/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '承認' }))
    expect(calls.some((c) => c.url.endsWith('/approve'))).toBe(true)
  })

  it('requires confirmation before starting training', async () => {
    const user = userEvent.setup()
    const calls = mockFetch(routes({ 'POST /api/training/runs': () => jsonResponse({ id: 'r'.repeat(32) }) }))
    render(<TrainingPage />)
    await user.click(screen.getByRole('tab', { name: '学習の実行' }))
    await user.click(await screen.findByRole('button', { name: '確認して学習を開始…' }))
    const dialog = screen.getByRole('dialog')
    const startBtn = within(dialog).getByRole('button', { name: '学習を開始する' })
    expect(startBtn).toBeDisabled()
    expect(within(dialog).getByText(/会話用の AI は一時的に使えません/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('checkbox'))
    await user.click(startBtn)
    const post = calls.find((c) => c.url === '/api/training/runs' && c.init?.method === 'POST')!
    expect(JSON.parse(String(post.init!.body))).toMatchObject({ base: 'qwen3-1.7b', confirmed: true })
  })

  it('blocks training when requirements are missing', async () => {
    const user = userEvent.setup()
    mockFetch(routes({ 'GET /api/training/environment': () => jsonResponse({ ...ENV, approved_examples: 2 }) }))
    render(<TrainingPage />)
    await user.click(screen.getByRole('tab', { name: '学習の実行' }))
    expect(await screen.findByText(/5 件以上必要です（現在 2 件）/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '確認して学習を開始…' })).toBeDisabled()
  })
})
