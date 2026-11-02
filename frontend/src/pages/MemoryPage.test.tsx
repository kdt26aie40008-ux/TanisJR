import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Memory } from '../api/types'
import { jsonResponse, mockFetch } from '../test/fetchMock'
import { MemoryPage } from './MemoryPage'

const STATS = { active: 1, pending: 1, unindexed: 0, embedding_model: 'e', embedding_available: true }
const MODEL_OK = {
  ollama_available: true,
  message: null,
  installed: [],
  configured_model: 'qwen3:8b',
  configured_model_installed: true,
  embedding_model: 'e',
  embedding_model_installed: true,
  catalog: [],
  storage_path: '',
  free_space_gb: 1,
}

function memory(overrides: Partial<Memory>): Memory {
  return {
    id: '1'.repeat(32),
    category: 'preference',
    content: 'ユーザーはラーメンが好き',
    source_type: 'conversation',
    source_conversation_id: 'c'.repeat(32),
    source_conversation_title: '昼ごはんの相談',
    source_excerpt: 'ラーメン大好き',
    importance: 5,
    sensitivity: 'general',
    status: 'active',
    confirmation_status: 'auto',
    indexed: true,
    created_at: '2026-11-02T00:00:00+00:00',
    updated_at: '2026-11-02T00:00:00+00:00',
    ...overrides,
  }
}

const ACTIVE = memory({})
const PENDING = memory({
  id: '2'.repeat(32),
  category: 'personal',
  content: 'ユーザーは東京在住',
  sensitivity: 'important',
  status: 'pending',
  confirmation_status: 'pending',
})

function baseRoutes() {
  return {
    'GET /api/memories/stats': () => jsonResponse(STATS),
    'GET /api/models/status': () => jsonResponse(MODEL_OK),
    'GET /api/memories?status=active': () => jsonResponse([ACTIVE]),
    'GET /api/memories?status=pending': () => jsonResponse([PENDING]),
  }
}

describe('MemoryPage', () => {
  it('lists memories with their source', async () => {
    const user = userEvent.setup()
    mockFetch(baseRoutes())
    render(<MemoryPage onChanged={vi.fn()} onOpenConversation={vi.fn()} />)
    expect(await screen.findByText('ユーザーはラーメンが好き')).toBeInTheDocument()
    await user.click(screen.getByText('出典: 会話「昼ごはんの相談」'))
    expect(screen.getByText('ラーメン大好き')).toBeInTheDocument()
  })

  it('deletes a memory only after confirmation', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      ...baseRoutes(),
      [`DELETE /api/memories/${ACTIVE.id}`]: () => jsonResponse({ deleted: true }),
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<MemoryPage onChanged={vi.fn()} onOpenConversation={vi.fn()} />)
    await screen.findByText('ユーザーはラーメンが好き')
    await user.click(screen.getByRole('button', { name: '削除' }))
    expect(calls.some((c) => c.init?.method === 'DELETE')).toBe(false)
    await user.click(screen.getByRole('button', { name: '削除' }))
    expect(confirm).toHaveBeenCalledTimes(2)
    expect(calls.some((c) => c.init?.method === 'DELETE')).toBe(true)
  })

  it('approves an edited pending memory', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      ...baseRoutes(),
      [`POST /api/memories/${PENDING.id}/approve`]: () => jsonResponse({ ...PENDING, status: 'active' }),
    })
    render(<MemoryPage onChanged={vi.fn()} onOpenConversation={vi.fn()} />)
    await user.click(await screen.findByRole('tab', { name: /承認待ち/ }))
    const box = await screen.findByLabelText(/保存する内容/)
    await user.clear(box)
    await user.type(box, 'ユーザーは東京都在住')
    await user.click(screen.getByRole('button', { name: '承認して保存' }))
    const approve = calls.find((c) => c.url.endsWith('/approve'))!
    expect(JSON.parse(String(approve.init!.body))).toEqual({ content: 'ユーザーは東京都在住' })
  })

  it('rejects a pending memory', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      ...baseRoutes(),
      [`POST /api/memories/${PENDING.id}/reject`]: () => jsonResponse({ deleted: true }),
    })
    render(<MemoryPage onChanged={vi.fn()} onOpenConversation={vi.fn()} />)
    await user.click(await screen.findByRole('tab', { name: /承認待ち/ }))
    await user.click(await screen.findByRole('button', { name: '拒否（削除）' }))
    expect(calls.some((c) => c.url.endsWith('/reject'))).toBe(true)
  })

  it('deletes a conversation with its memories when chosen', async () => {
    const user = userEvent.setup()
    const conv = { id: 'c'.repeat(32), title: '昼ごはんの相談', message_count: 4, created_at: '', updated_at: '' }
    const calls = mockFetch({
      ...baseRoutes(),
      'GET /api/conversations': () => jsonResponse([conv]),
      [`DELETE /api/conversations/${conv.id}?delete_memories=true`]: () => jsonResponse({ deleted: true }),
    })
    render(<MemoryPage onChanged={vi.fn()} onOpenConversation={vi.fn()} />)
    await user.click(await screen.findByRole('tab', { name: '会話履歴' }))
    await user.click(await screen.findByRole('button', { name: '削除' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('checkbox'))
    await user.click(within(dialog).getByRole('button', { name: '削除する' }))
    expect(calls.some((c) => c.url.endsWith('delete_memories=true'))).toBe(true)
  })
})
