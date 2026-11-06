/**
 * 数式の書き方をそろえる。AI は \( … \) や \[ … \] でも数式を書くので、表示用に $ … $ / $$ … $$ にする。
 */
export function normalizeMath(text: string): string {
  return text
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, body: string) => `\n$$\n${body.trim()}\n$$\n`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, body: string) => `$${body.trim()}$`)
    .replace(/\$\$([^\n$]+?)\$\$/g, (_, body: string) => `\n$$\n${body.trim()}\n$$\n`)
    .replace(/(^|[^$\\])\$ +([^$\n]+?) +\$(?!\$)/g, (_, before: string, body: string) => `${before}$${body}$`)
}

// 読み上げ用: LaTeX のコマンドを日本語の読みにする
const COMMANDS: [RegExp, string][] = [
  [/\\pm/g, 'プラスマイナス'],
  [/\\mp/g, 'マイナスプラス'],
  [/\\times/g, 'かける'],
  [/\\cdot/g, 'かける'],
  [/\\div/g, 'わる'],
  [/\\neq|\\ne\b/g, 'ノットイコール'],
  [/\\leq?\b/g, '以下'],
  [/\\geq?\b/g, '以上'],
  [/\\approx/g, 'ニアリーイコール'],
  [/\\infty/g, '無限大'],
  [/\\int/g, 'インテグラル'],
  [/\\sum/g, 'シグマ'],
  [/\\lim/g, 'リミット'],
  [/\\to|\\rightarrow/g, 'から'],
  [/\\pi/g, 'パイ'],
  [/\\theta/g, 'シータ'],
  [/\\alpha/g, 'アルファ'],
  [/\\beta/g, 'ベータ'],
  [/\\Delta/g, 'デルタ'],
  [/\\sin/g, 'サイン'],
  [/\\cos/g, 'コサイン'],
  [/\\tan/g, 'タンジェント'],
  [/\\log/g, 'ログ'],
]

/** 1つの数式（$ の中身）を読みやすい言葉にする */
export function speakFormula(tex: string): string {
  let s = tex.replace(/\\(left|right|big|Big|displaystyle|quad|qquad)(?![a-zA-Z])|\\[,;!]/g, ' ')
  // 中から順に置き換えるため、入れ子がなくなるまで繰り返す
  for (let i = 0; i < 5; i++) {
    s = s
      .replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, ' $2ぶんの$1 ')
      .replace(/\\sqrt\s*\{([^{}]*)\}/g, ' ルート$1 ')
      .replace(/\^\{2\}|\^2(?![0-9])/g, 'の2乗')
      .replace(/\^\{3\}|\^3(?![0-9])/g, 'の3乗')
      .replace(/\^\{([^{}]*)\}/g, 'の$1乗')
      .replace(/\^([0-9a-zA-Z])/g, 'の$1乗')
      .replace(/_\{([^{}]*)\}|_([0-9a-zA-Z])/g, '$1$2')
  }
  for (const [pattern, word] of COMMANDS) s = s.replace(pattern, ` ${word} `)
  return s
    .replace(/\\[a-zA-Z]+/g, ' ')
    .replace(/[{}]/g, '')
    .replace(/=/g, ' イコール ')
    .replace(/\+/g, ' たす ')
    .replace(/(^|[^ぶ])-/g, '$1 ひく ')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * 文ごとに届く返事を読み上げ用にする。コードブロック（``` で囲まれた部分）は文をまたぐので、
 * 中にいるかどうかを覚えておき、コードの行は読まない。
 */
export class SpeechFilter {
  private inCode = false

  /** 読み上げる文を返す。読むものがなければ空文字 */
  next(sentence: string): string {
    const parts = sentence.split('```')
    let spoken = ''
    parts.forEach((part, i) => {
      if (i > 0) this.inCode = !this.inCode
      if (!this.inCode) spoken += part
    })
    // コードの直後にある言語名（```python の python）は読まない
    return toSpeech(spoken.replace(/^[a-zA-Z0-9+#-]+\s*$/, ''))
  }
}

/** 読み上げる文から、数式・書式の記号・コードを取り除いて、声で聞きやすい文にする */
export function toSpeech(text: string): string {
  return normalizeMath(text)
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, tex: string) => ` ${speakFormula(tex)} `)
    .replace(/\$([^$\n]+?)\$/g, (_, tex: string) => ` ${speakFormula(tex)} `)
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, '$1$2')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[ \t]+/g, ' ')
    .trim()
}
