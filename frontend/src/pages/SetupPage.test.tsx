import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { jsonResponse, mockFetch } from '../test/fetchMock'
import { SetupPage } from './SetupPage'

const QUESTIONS = {
  questions: [
    { key: 'setup.q1_identity', text: 'あなたは誰ですか？' },
    { key: 'setup.q2_personality', text: 'あなたはどんな性格で嫌いなのか好きなのか自分について詳しく教えて下さい' },
    { key: 'setup.q3_ai_name', text: '私の名前をどうしますか？' },
  ],
  consent: { version: 'v1', purpose: '利用目的の説明', stored_items: ['回答'], notes: ['ローカル保存'] },
}

describe('SetupPage', () => {
  it('asks the three questions in order and saves with consent', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      'GET /api/setup/questions': () => jsonResponse(QUESTIONS),
      'POST /api/setup/complete': (_url, init) => {
        const body = JSON.parse(String(init?.body))
        return jsonResponse({ completed: true, ai_name: body.ai_name })
      },
    })
    const onComplete = vi.fn()
    render(<SetupPage onComplete={onComplete} />)

    const start = await screen.findByRole('button', { name: '同意して始める' })
    expect(start).toBeDisabled()
    expect(screen.getByText('利用目的の説明')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox'))
    await user.click(start)

    const answers = ['山田です', '好奇心が強い', 'タニスにして']
    for (let i = 0; i < 3; i++) {
      expect(screen.getByTestId('current-question')).toHaveTextContent(QUESTIONS.questions[i].text)
      await user.type(screen.getByLabelText('回答'), answers[i])
      await user.click(screen.getByRole('button', { name: '次へ' }))
    }

    const nameInput = screen.getByLabelText(/AIの名前/)
    expect(nameInput).toHaveValue('タニス')
    await user.click(screen.getByRole('button', { name: 'この内容で保存して始める' }))

    const post = calls.find((c) => c.init?.method === 'POST')!
    expect(JSON.parse(String(post.init!.body))).toEqual({ consent: true, answers, ai_name: 'タニス' })
    expect(onComplete).toHaveBeenCalledWith('タニス')
  })

  it('does not advance with an empty answer', async () => {
    const user = userEvent.setup()
    mockFetch({ 'GET /api/setup/questions': () => jsonResponse(QUESTIONS) })
    render(<SetupPage onComplete={vi.fn()} />)
    await user.click(await screen.findByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: '同意して始める' }))
    await user.click(screen.getByRole('button', { name: '次へ' }))
    expect(screen.getByRole('alert')).toHaveTextContent('回答を入力してください。')
    expect(screen.getByTestId('current-question')).toHaveTextContent('あなたは誰ですか？')
  })

  it('shows server error messages in Japanese', async () => {
    const user = userEvent.setup()
    mockFetch({
      'GET /api/setup/questions': () => jsonResponse(QUESTIONS),
      'POST /api/setup/complete': () =>
        jsonResponse({ detail: { code: 'setup_already_completed', message: '初回設定はすでに完了しています。' } }, 409),
    })
    render(<SetupPage onComplete={vi.fn()} />)
    await user.click(await screen.findByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: '同意して始める' }))
    for (const a of ['a', 'b', 'c']) {
      await user.type(screen.getByLabelText('回答'), a)
      await user.click(screen.getByRole('button', { name: '次へ' }))
    }
    await user.click(screen.getByRole('button', { name: 'この内容で保存して始める' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('初回設定はすでに完了しています。')
  })

  it('shows a connection error when the server is down', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    render(<SetupPage onComplete={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('サーバーに接続できません')
  })
})
