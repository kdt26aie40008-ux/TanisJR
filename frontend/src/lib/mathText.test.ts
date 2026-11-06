import { describe, expect, it } from 'vitest'
import { normalizeMath, SpeechFilter, speakFormula, toSpeech } from './mathText'

describe('normalizeMath', () => {
  it('turns \\( \\) and \\[ \\] into dollar delimiters', () => {
    expect(normalizeMath('式は \\(x^2\\) です')).toBe('式は $x^2$ です')
    expect(normalizeMath('\\[ a+b \\]')).toContain('$$\na+b\n$$')
  })

  it('puts one-line $$ … $$ on its own block and trims spaces inside $ … $', () => {
    expect(normalizeMath('答えは $$ \\frac{x^3}{3} $$ だよ')).toContain('\n$$\n\\frac{x^3}{3}\n$$\n')
    expect(normalizeMath('方程式 $ ax^2 + bx + c = 0 $ の解')).toBe('方程式 $ax^2 + bx + c = 0$ の解')
  })

  it('leaves prices and plain text alone', () => {
    expect(normalizeMath('これは 100 円です')).toBe('これは 100 円です')
  })
})

describe('speakFormula', () => {
  it('reads fractions, roots and powers in Japanese', () => {
    expect(speakFormula('x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}')).toBe(
      'x イコール 2aぶんの ひく b プラスマイナス ルートbの2乗 ひく 4ac',
    )
    expect(speakFormula('\\int x^2 \\, dx = \\frac{x^3}{3} + C')).toBe('インテグラル xの2乗 dx イコール 3ぶんのxの3乗 たす C')
  })
})

describe('SpeechFilter', () => {
  it('skips code blocks that span several sentences', () => {
    const f = new SpeechFilter()
    const spoken = ['例えばこう書くよ。', '```python', 'my_list.reverse()', '```', 'これで逆順になる。'].map((s) => f.next(s))
    expect(spoken).toEqual(['例えばこう書くよ。', '', '', '', 'これで逆順になる。'])
  })
})

describe('toSpeech', () => {
  it('reads formulas and drops markdown symbols and code', () => {
    const text = '公式は **$a^2 + b^2 = c^2$** だよ。\n```python\nprint(1)\n```\n`reverse()` を使う'
    const spoken = toSpeech(text)
    expect(spoken).toContain('aの2乗 たす bの2乗 イコール cの2乗')
    expect(spoken).not.toMatch(/[$*`\\]|print/)
    expect(spoken).toContain('reverse() を使う')
  })
})
