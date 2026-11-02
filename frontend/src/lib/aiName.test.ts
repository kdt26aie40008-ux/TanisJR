import { describe, expect, it } from 'vitest'
import { suggestAiName } from './aiName'

describe('suggestAiName', () => {
  it.each([
    ['タニス', 'タニス'],
    ['タニスにして', 'タニス'],
    ['タニスにしてください。', 'タニス'],
    ['名前はエフがいい', 'エフ'],
    ['「ジュニア」でお願いします', 'ジュニア'],
    ['エフって呼ぶ', 'エフ'],
    ['F', 'F'],
  ])('%s → %s', (answer, expected) => {
    expect(suggestAiName(answer)).toBe(expected)
  })

  it('limits length to 32', () => {
    expect(suggestAiName('あ'.repeat(50))).toHaveLength(32)
  })
})
