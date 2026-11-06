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

const BIG_OPERATOR = /\\(int|iint|oint|sum|prod|lim|frac)(?![a-zA-Z])/

/**
 * 表示用: 文中の数式に積分・総和・分数などがあると、文の高さに押し込まれて小さく潰れるため、
 * その数式だけ別行の数式と同じ大きさ（\displaystyle）で描く。積分の dx の前には少し間をあける。
 */
export function readableMath(text: string): string {
  return normalizeMath(text).replace(/(^|[^$\\])\$([^$\n]+?)\$(?!\$)/g, (whole, before: string, body: string) => {
    if (!BIG_OPERATOR.test(body)) return whole
    const spaced = /\\i+nt|\\oint/.test(body) ? body.replace(/(^|[^\\a-zA-Z,])\s*d([a-zA-Z])(?![a-zA-Z])/g, '$1\\,d$2') : body
    return `${before}$\\displaystyle ${spaced}$`
  })
}

/** 読み上げ用: 数を声で聞き取りやすくする（乗は「のり」と読まれないよう、ひらがなで書く） */
const power = (exponent: string) => {
  const e = exponent.trim()
  if (e === '-1') return 'のマイナス1じょう'
  if (e === '\\prime' || e === "'") return 'ダッシュ'
  return `の${e.replace(/^-/, 'マイナス')}じょう`
}

// ²³ などの上付き数字（数式の外にも書かれる）
const SUPERSCRIPTS: Record<string, string> = {
  '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9', '⁻': '-',
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
  let s = tex.replace(/\\(left|right|big|Big|bigg|Bigg|displaystyle|textstyle|quad|qquad|limits)(?![a-zA-Z])|\\[,;:!]/g, ' ')
  // 積分・総和・極限の上下の数は「乗」ではなく範囲として読む（∫_0^1 → 0から1までの積分）
  const bound = String.raw`(?:\{([^{}]*)\}|(\\?[0-9a-zA-Z]+))`
  s = s
    .replace(new RegExp(String.raw`\\(i+nt|oint)\s*_\s*${bound}\s*\^\s*${bound}`, 'g'), (_, _op, a1, a2, b1, b2) =>
      ` ${a1 ?? a2}から${b1 ?? b2}までの積分 `,
    )
    .replace(new RegExp(String.raw`\\sum\s*_\s*${bound}\s*\^\s*${bound}`, 'g'), (_, a1, a2, b1, b2) =>
      ` ${a1 ?? a2}から${b1 ?? b2}までの和 `,
    )
    .replace(new RegExp(String.raw`\\lim\s*_\s*${bound}`, 'g'), (_, a1, a2) => ` ${a1 ?? a2}のときの極限 `)
    // 積分の終わりの dx は「ディーエックス」
    .replace(/(^|[^\\a-zA-Z])d([a-zA-Z])(?![a-zA-Z])/g, (_, before: string, v: string) => `${before} ディー${v} `)
  // 中から順に置き換えるため、入れ子がなくなるまで繰り返す
  for (let i = 0; i < 5; i++) {
    s = s
      .replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, ' $2ぶんの$1 ')
      .replace(/\\sqrt\s*\[([^\]]*)\]\s*\{([^{}]*)\}/g, ' $1じょうこん$2 ')
      .replace(/\\sqrt\s*\{([^{}]*)\}/g, ' ルート$1 ')
      .replace(/\^\{([^{}]*)\}/g, (_, e: string) => power(e))
      // ^22 のように波かっこのない数は、2桁以上でもまとめて読む
      .replace(/\^(-?[0-9]+|[a-zA-Z]|\\prime)/g, (_, e: string) => power(e))
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
    // 数式の外に書かれた累乗（x²、x^22、10⁻³）も読む
    .replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+/g, (sup: string) => power([...sup].map((c) => SUPERSCRIPTS[c]).join('')))
    .replace(/([0-9a-zA-Z)])\^\{?(-?[0-9]+)\}?/g, (_, base: string, e: string) => `${base}${power(e)}`)
    .replace(/√\s*([0-9a-zA-Z]+)/g, 'ルート$1')
    .replace(/∫/g, ' 積分 ')
    .replace(/π/g, 'パイ')
    .replace(/×/g, ' かける ')
    .replace(/÷/g, ' わる ')
    .replace(/≦|≤/g, ' 以下 ')
    .replace(/≧|≥/g, ' 以上 ')
    .replace(/≠/g, ' ノットイコール ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, '$1$2')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[ \t]+/g, ' ')
    .trim()
}
