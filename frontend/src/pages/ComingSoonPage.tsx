import type { RouteDef } from '../routes'

/** 未実装の画面。機能があるように見せないため、操作要素は置かない。 */
export function ComingSoonPage({ route }: { route: RouteDef }) {
  return (
    <section className="page">
      <h1>{route.label}</h1>
      <div className="panel muted-panel">
        <p>
          この画面は <strong>Phase {route.plannedPhase}</strong> で実装予定です。現在は利用できません。
        </p>
      </div>
    </section>
  )
}
