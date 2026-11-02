import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { CalendarOperation } from '../../api/types'
import { jsonResponse, mockFetch } from '../../test/fetchMock'
import { OperationCard } from './OperationCard'

const OP: CalendarOperation = {
  id: 'a'.repeat(32),
  action: 'create',
  event_id: null,
  draft: {
    summary: '歯医者',
    all_day: false,
    start: '2026-11-03T10:00',
    end: '2026-11-03T11:00',
    location: '駅前',
    description: '',
    reminder_minutes: null,
  },
  target: null,
  source: 'ai',
  status: 'pending',
  error: null,
  result_event_id: null,
  created_at: '',
  decided_at: null,
}

describe('OperationCard', () => {
  it('shows the AI proposal and only executes after approval', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      [`POST /api/calendar/operations/${OP.id}/approve`]: () => jsonResponse({ ...OP, status: 'done' }),
    })
    render(<OperationCard operation={OP} />)
    expect(screen.getByText('AIの提案')).toBeInTheDocument()
    expect(screen.getByText('歯医者')).toBeInTheDocument()
    expect(screen.getByText('11/3（火） 10:00〜11:00')).toBeInTheDocument()
    expect(calls).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: '承認して実行' }))
    expect(await screen.findByText('実行しました')).toBeInTheDocument()
    expect(calls).toHaveLength(1)
  })

  it('reject does not execute', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      [`POST /api/calendar/operations/${OP.id}/reject`]: () => jsonResponse({ ...OP, status: 'rejected' }),
    })
    render(<OperationCard operation={OP} />)
    await user.click(screen.getByRole('button', { name: '却下' }))
    expect(await screen.findByText('却下しました')).toBeInTheDocument()
    expect(calls.map((c) => c.url)).toEqual([`/api/calendar/operations/${OP.id}/reject`])
  })

  it('asks again before deleting', async () => {
    const user = userEvent.setup()
    const del: CalendarOperation = {
      ...OP,
      action: 'delete',
      draft: null,
      event_id: 'ev1',
      target: { id: 'ev1', summary: '会議', all_day: false, start: '2026-11-03T09:00:00+09:00', end: '2026-11-03T10:00:00+09:00', location: '', description: '', html_link: '', notify_minutes: null },
    }
    const calls = mockFetch({
      [`POST /api/calendar/operations/${OP.id}/approve`]: () => jsonResponse({ ...del, status: 'done' }),
    })
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    render(<OperationCard operation={del} />)
    await user.click(screen.getByRole('button', { name: '承認して実行' }))
    expect(calls).toHaveLength(0)
  })
})
