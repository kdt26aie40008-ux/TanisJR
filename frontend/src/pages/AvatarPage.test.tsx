import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Avatar } from '../api/types'
import { jsonResponse, mockFetch } from '../test/fetchMock'
import { AvatarPage } from './AvatarPage'

const AVATAR: Avatar = {
  id: 'a'.repeat(32),
  name: 'Seed-san',
  size: 10_917_800,
  is_placeholder: true,
  vrm_version: '1.0',
  meta: {
    name: 'Seed-san',
    authors: 'VirtualCast, Inc.',
    copyright: 'VirtualCast, Inc.',
    license_url: 'https://vrm.dev/licenses/1.0/',
    avatar_permission: 'everyone',
    commercial_usage: 'corporation',
    credit_required: true,
    allow_redistribution: true,
    modification: 'allowModificationRedistribution',
  },
  created_at: '2026-11-02T00:00:00+00:00',
  builtin: false,
}

const BUILTIN: Avatar = { ...AVATAR, id: 'b'.repeat(32), name: '標準アバター（男性）', is_placeholder: false, created_at: '', builtin: true }

describe('AvatarPage', () => {
  it('marks placeholder models and shows the required credit', async () => {
    mockFetch({ 'GET /api/avatars': () => jsonResponse({ avatars: [AVATAR], active_id: AVATAR.id }) })
    render(<AvatarPage />)
    expect(await screen.findByText('仮モデル', { selector: '.placeholder-badge' })).toBeInTheDocument()
    expect(screen.getByText('Seed-san / 作者: VirtualCast, Inc.')).toBeInTheDocument()
    // jsdom には WebGL が無いので、分かりやすいメッセージを出す
    expect(await screen.findByText('この環境では3D表示（WebGL）が使えません。')).toBeInTheDocument()
  })

  it('lets built-in avatars be selected but not edited or deleted', async () => {
    const user = userEvent.setup()
    let activated = ''
    mockFetch({
      'GET /api/avatars': () => jsonResponse({ avatars: [AVATAR, BUILTIN], active_id: AVATAR.id }),
      [`POST /api/avatars/${BUILTIN.id}/activate`]: () => {
        activated = BUILTIN.id
        return jsonResponse({ active_id: BUILTIN.id })
      },
    })
    render(<AvatarPage />)
    const item = (await screen.findByText('標準アバター（男性）')).closest('li') as HTMLElement
    expect(within(item).getByText('標準')).toBeInTheDocument()
    expect(within(item).queryByRole('button', { name: '削除' })).toBeNull()
    expect(within(item).queryByRole('button', { name: '名前を変更' })).toBeNull()
    await user.click(within(item).getByRole('button', { name: '使用する' }))
    expect(activated).toBe(BUILTIN.id)
  })

  it('shows the server validation message for a non-VRM file', async () => {
    const user = userEvent.setup()
    mockFetch({
      'GET /api/avatars': () => jsonResponse({ avatars: [], active_id: null }),
      'POST /api/avatars?name=&placeholder=true': () =>
        jsonResponse({ detail: { code: 'invalid_avatar', message: 'VRMファイル（.vrm）ではありません。' } }, 400),
    })
    render(<AvatarPage />)
    const file = new File(['not a vrm'], 'model.vrm', { type: 'application/octet-stream' })
    await user.upload(screen.getByLabelText(/VRM ファイル/), file)
    await user.click(screen.getByRole('button', { name: '登録する' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('VRMファイル（.vrm）ではありません。')
  })
})
