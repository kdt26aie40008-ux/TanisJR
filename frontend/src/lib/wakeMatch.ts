/** カタカナをひらがなにし、空白・記号を除いて比べやすくする */
export function normalizeSpeech(text: string): string {
  return text
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60))
    .replace(/[\s、。，．,.!?！？「」『』…・〜~ー-]/g, '')
}

const CALLS = ['ねえ', 'ねぇ', 'ねー', 'おーい', 'おい', 'hey', 'ヘイ']

export interface WakeMatch {
  /** 名前を呼ばれた */
  matched: boolean
  /** 名前のあとに続けて話した内容（「ねえタニス、明日の予定は？」の「明日の予定は？」） */
  rest: string
}

/**
 * 聞き取った文に、AI の名前（または読み）が含まれているか調べる。
 * 名前の前の呼びかけ（「ねえ」など）はあってもなくてもよい。
 */
export function matchWake(text: string, names: string[]): WakeMatch {
  // 1文字の名前は、ひらがな・英字だと他の言葉に紛れるので使わない。漢字1文字（「漆」など）は使う
  // （読みを「うるし」と登録していても、音声認識が漢字で書くことがあるため）
  const keys = names
    .map(normalizeSpeech)
    .filter((n) => n.length >= 2 || /^[\p{Script=Han}]$/u.test(n))
  // 元の文の位置を保ったまま比べるため、1文字ずつ正規化した位置の対応表を作る
  const map: number[] = []
  let normalized = ''
  for (let i = 0; i < text.length; i++) {
    const part = normalizeSpeech(text[i])
    for (let j = 0; j < part.length; j++) map.push(i)
    normalized += part
  }
  for (const key of keys) {
    const at = normalized.indexOf(key)
    if (at < 0) continue
    const endInText = map[at + key.length - 1] + 1
    const rest = text
      .slice(endInText)
      .replace(/^[\s、。，,.!?！？…ー〜~]+/, '')
      .replace(/^(さん|ちゃん|くん)[\s、,]*/, '')
      .trim()
    return { matched: true, rest: CALLS.includes(normalizeSpeech(rest)) ? '' : rest }
  }
  return { matched: false, rest: '' }
}
