import { describe, expect, it } from 'vitest'
import { matchWake, normalizeSpeech } from './wakeMatch'

describe('matchWake', () => {
  const names = ['炭谷', 'すみたに']

  it('finds the name in kanji, hiragana or katakana', () => {
    expect(matchWake('ねえ、炭谷', names)).toEqual({ matched: true, rest: '' })
    expect(matchWake('ねえすみたに', names).matched).toBe(true)
    expect(matchWake('ねえ スミタニ。', names).matched).toBe(true)
  })

  it('keeps what was said after the name as the message', () => {
    expect(matchWake('ねえ炭谷、明日の予定は？', names)).toEqual({ matched: true, rest: '明日の予定は？' })
    expect(matchWake('スミタニさん、今何時？', names)).toEqual({ matched: true, rest: '今何時？' })
  })

  it('matches a romaji name through its reading (real transcript of a synthesized voice)', () => {
    // 「TanisJr」は聞き取ると「タニスジュニア」になるため、読みを登録しておく
    expect(matchWake('ねぇタニスジュニア、明日の予定を教えて。', ['TanisJr'])).toEqual({ matched: false, rest: '' })
    expect(matchWake('ねぇタニスジュニア、明日の予定を教えて。', ['TanisJr', 'たにすじゅにあ'])).toEqual({
      matched: true,
      rest: '明日の予定を教えて。',
    })
  })

  it('ignores speech without the name', () => {
    expect(matchWake('ねえ、ちょっと聞いて', names)).toEqual({ matched: false, rest: '' })
    expect(matchWake('', names).matched).toBe(false)
  })

  it('ignores names too short to match reliably', () => {
    expect(matchWake('あいうえお', ['あ']).matched).toBe(false)
  })

  it('accepts a one-kanji name, since speech recognition may write the reading in kanji', () => {
    expect(matchWake('ねえ、漆。', ['漆', 'うるし'])).toEqual({ matched: true, rest: '' })
    expect(matchWake('ねえウルシ、明日の予定は？', ['漆', 'うるし'])).toEqual({ matched: true, rest: '明日の予定は？' })
  })

  it('normalizes width, case and symbols', () => {
    expect(normalizeSpeech('ＴＡＮＩＳ、タニス！')).toBe('tanisたにす')
  })
})
