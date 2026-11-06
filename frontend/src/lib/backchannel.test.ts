import { describe, expect, it } from 'vitest'
import { chooseBackchannel } from './backchannel'

const first = () => 0

describe('chooseBackchannel', () => {
  it('matches the mood of what was said', () => {
    expect(chooseBackchannel('今日めっちゃ疲れた', '', first)).toBe('そっか…。')
    expect(chooseBackchannel('テストに合格したよ', '', first)).toBe('おお、')
    expect(chooseBackchannel('明日の10時に歯医者入れて', '', first)).toBe('うん、わかった。')
    expect(chooseBackchannel('積分ってどうやるの？', '', first)).toBe('えっとね、')
    expect(chooseBackchannel('昨日カレーを作ったんだ', '', first)).toBe('うん。')
  })

  it('stays quiet for greetings and very short words', () => {
    expect(chooseBackchannel('おはよう', '', first)).toBeNull()
    expect(chooseBackchannel('こんにちは、元気？', '', first)).toBeNull()
    expect(chooseBackchannel('うん', '', first)).toBeNull()
  })

  it('does not repeat the previous one', () => {
    expect(chooseBackchannel('今日めっちゃ疲れた', 'そっか…。', first)).toBe('うん…。')
  })
})
