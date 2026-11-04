import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AppSettings } from '../api/types'
import { BehaviorSettings } from './BehaviorSettings'

const SETTINGS = {
  behavior_nod: true,
  behavior_gaze: true,
  behavior_backchannel: true,
  behavior_barge_in: false,
  behavior_sentence_emotion: true,
} as AppSettings

describe('BehaviorSettings', () => {
  it('shows each behavior as its own switch', async () => {
    const user = userEvent.setup()
    const update = vi.fn()
    render(<BehaviorSettings settings={SETTINGS} update={update} />)
    expect(screen.getAllByRole('switch')).toHaveLength(5)
    expect(screen.getByRole('switch', { name: '聞いている間うなずく' })).toBeChecked()
    expect(screen.getByRole('switch', { name: '話の途中で割り込める' })).not.toBeChecked()
    // 割り込みはスピーカーの音を拾うおそれがあることを説明する
    expect(screen.getByText(/ヘッドホンでの利用をおすすめします/)).toBeInTheDocument()

    await user.click(screen.getByRole('switch', { name: '聞いている間うなずく' }))
    expect(update).toHaveBeenCalledWith('behavior_nod', false)
    await user.click(screen.getByRole('switch', { name: '話の途中で割り込める' }))
    expect(update).toHaveBeenCalledWith('behavior_barge_in', true)
  })
})
