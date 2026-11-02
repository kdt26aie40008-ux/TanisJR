/**
 * 「私の名前をどうしますか？」への回答から名前の候補を取り出す。
 * あくまで候補であり、確定前に画面でユーザーが確認・修正する。
 */
export function suggestAiName(answer: string): string {
  let text = answer.trim()
  const quoted = text.match(/[「『"“](.+?)[」』"”]/)
  if (quoted) return quoted[1].trim().slice(0, 32)

  text = text
    .replace(/^(あなたの)?(名前は|なまえは)/, '')
    .replace(/[。．.！!？?\s]+$/, '')
    .replace(/(って|と)?(呼ぶ|呼びます|名付けます|名付ける)$/, '')
    .replace(/(に|で)(して(ください|下さい|ほしい|欲しい)?|します|お願いします|お願い|いい|いいです|決めた|決めます)$/, '')
    .replace(/(が|は)?(いい|良い)(です|な)?$/, '')
    .replace(/(です|だ|かな)$/, '')
    .trim()
  return text.slice(0, 32)
}
