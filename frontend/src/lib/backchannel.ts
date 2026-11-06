/**
 * 声で話し終えたあと、返事を考える前に入れる相づちを、話した内容に合わせて選ぶ。
 * 合う相づちがないとき（あいさつ・短すぎる発話など）は入れない（null）。
 */
const KINDS: { test: RegExp; words: string[] }[] = [
  // あいさつには、相づちを入れずにそのまま返事をする
  { test: /^(おはよう|こんにちは|こんばんは|やあ|ただいま|おやすみ|ありがとう|いってきます|はじめまして)/, words: [] },
  // つらい・しんどい話には、静かに受け止める
  { test: /(疲れ|つかれ|しんど|つらい|辛い|悲し|かなし|最悪|落ち込|へこ|嫌だ|いやだ|しんどい|眠い|ねむい|寂し|さびし|痛い|いたい)/, words: ['そっか…。', 'うん…。', 'そうなんだ…。'] },
  // うれしい話には、明るく
  { test: /(嬉し|うれし|楽し|たのし|やった|最高|よかった|良かった|合格|できた|受かった)/, words: ['おお、', 'いいね。', 'よかったね。'] },
  // 頼みごとには、引き受ける
  { test: /(して(ほしい|くれ|ください|ね)?$|入れて|お願い|おねがい|やって|調べて|作って|教えて|消して|変えて|決めて|覚えて)/, words: ['うん、わかった。', 'オッケー。', 'まかせて。'] },
  // 問いかけには、考える間
  { test: /([?？]|かな$|かな[。、]|の$|って何|ってなに|なに|何|どう|いつ|どこ|誰|だれ|なんで|なぜ|どれ|どっち|いくら|ある[？?]?$|ない[？?]?$)/, words: ['えっとね、', 'そうだなあ、', 'うーんと、'] },
]
const DEFAULT_WORDS = ['うん。', 'うんうん。', 'なるほど。']

/** 相づちを選ぶ。前回と同じものは続けない。入れないときは null */
export function chooseBackchannel(text: string, previous = '', random: () => number = Math.random): string | null {
  const t = text.trim().replace(/[。、！!\s]+$/, '')
  if (t.length < 4) return null
  const kind = KINDS.find((k) => k.test.test(t))
  const words = kind ? kind.words : DEFAULT_WORDS
  if (words.length === 0) return null
  const choices = words.length > 1 ? words.filter((w) => w !== previous) : words
  return choices[Math.floor(random() * choices.length)]
}
