export type Emotion = 'neutral' | 'happy' | 'sad' | 'surprised' | 'relaxed' | 'angry'

const RULES: [Exclude<Emotion, 'neutral'>, RegExp][] = [
  ['surprised', /(えっ|ええっ|驚|びっくり|まさか|！？|!\?|本当に？)/g],
  ['sad', /(残念|悲し|ごめん|申し訳|つらい|辛かった|寂し|心配)/g],
  ['angry', /(許せない|ひどい|腹が立)/g],
  ['happy', /(嬉し|うれし|楽し|いいね|素敵|すごい|おめでとう|よかった|最高|ありがとう|笑|！)/g],
  ['relaxed', /(ゆっくり|のんびり|落ち着|ほっと|大丈夫)/g],
]

/** 応答文から表情を簡易的に推定する（キーワードの出現数による。精度は高くない）。 */
export function detectEmotion(text: string): Emotion {
  let best: Emotion = 'neutral'
  let bestScore = 0
  for (const [emotion, pattern] of RULES) {
    const score = (text.match(pattern) ?? []).length * (emotion === 'happy' ? 1 : 1.5)
    if (score > bestScore) {
      best = emotion
      bestScore = score
    }
  }
  return best
}
