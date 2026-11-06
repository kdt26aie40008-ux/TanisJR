import { useId, type ReactNode } from 'react'
import { api } from '../../api/client'
import type { Scene } from '../../api/types'
import { sceneLook, type SceneLook } from '../../lib/sceneLook'

/**
 * アバターの後ろの景色。部屋・カフェ・公園・街をコードで描き、時間帯と天気で空の色・明かり・雨や雪を変える。
 * 自分で用意した画像のときは、画像に時間帯の色をかけ、屋外なら雨や雪を重ねる。
 */
export function SceneBackdrop({ scene }: { scene: Scene | null }) {
  const uid = useId().replace(/:/g, '')
  if (!scene) return <div className="scene-backdrop scene-empty" aria-hidden />
  const look = sceneLook(scene.period, scene.sky, scene.indoor)
  const ids = { sky: `sky-${uid}`, rain: `rain-${uid}`, snow: `snow-${uid}`, glow: `glow-${uid}`, win: `win-${uid}`, fog: `fog-${uid}` }

  if (scene.kind === 'custom' && scene.background_id) {
    return (
      <div className="scene-backdrop" aria-hidden data-period={scene.period}>
        <img className="scene-image" src={api.backgroundFileUrl(scene.background_id)} alt="" />
        <div className="scene-tint" style={{ background: look.tint }} />
        {!scene.indoor && (
          <svg className="scene-weather" viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMax slice">
            <Defs ids={ids} look={look} />
            <Weather ids={ids} look={look} x={0} y={0} w={1600} h={1000} />
          </svg>
        )}
        {look.thunder && !scene.indoor && <div className="scene-flash" />}
      </div>
    )
  }

  const Body = { room: Room, cafe: Cafe, park: Park, street: Street }[scene.kind === 'custom' ? 'room' : scene.kind]
  return (
    <div className="scene-backdrop" aria-hidden data-period={scene.period}>
      <svg className="scene-svg" viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMax slice">
        <Defs ids={ids} look={look} />
        <Body ids={ids} look={look} />
      </svg>
      {look.thunder && <div className={`scene-flash${scene.indoor ? ' soft' : ''}`} />}
    </div>
  )
}

type Ids = Record<'sky' | 'rain' | 'snow' | 'glow' | 'win' | 'fog', string>
interface Part {
  ids: Ids
  look: SceneLook
}

function Defs({ ids, look }: Part) {
  return (
    <defs>
      <linearGradient id={ids.sky} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor={look.skyTop} />
        <stop offset="1" stopColor={look.skyBottom} />
      </linearGradient>
      <radialGradient id={ids.glow}>
        <stop offset="0" stopColor="#ffd9a0" stopOpacity="0.75" />
        <stop offset="1" stopColor="#ffd9a0" stopOpacity="0" />
      </radialGradient>
      <linearGradient id={ids.fog} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#ffffff" stopOpacity="0.15" />
        <stop offset="1" stopColor="#ffffff" stopOpacity="0.6" />
      </linearGradient>
      {/* 雨: 斜めの線を下へ流す */}
      <pattern id={ids.rain} width="60" height="120" patternUnits="userSpaceOnUse" patternTransform="rotate(12)">
        <line x1="10" y1="0" x2="10" y2="34" stroke="#dfe8f2" strokeWidth="2" strokeOpacity="0.55" />
        <line x1="40" y1="60" x2="40" y2="92" stroke="#dfe8f2" strokeWidth="2" strokeOpacity="0.45" />
        <animateTransform attributeName="patternTransform" type="translate" from="0 0" to="0 120" dur="0.45s" repeatCount="indefinite" additive="sum" />
      </pattern>
      {/* 雪: 小さな丸をゆっくり下へ */}
      <pattern id={ids.snow} width="90" height="90" patternUnits="userSpaceOnUse">
        <circle cx="15" cy="20" r="3.5" fill="#fff" fillOpacity="0.9" />
        <circle cx="60" cy="55" r="2.5" fill="#fff" fillOpacity="0.8" />
        <circle cx="40" cy="80" r="2" fill="#fff" fillOpacity="0.7" />
        <animateTransform attributeName="patternTransform" type="translate" from="0 0" to="20 90" dur="4s" repeatCount="indefinite" />
      </pattern>
    </defs>
  )
}

/** 空（太陽・月・星・雲） */
function SkyArea({ ids, look, x, y, w, h }: Part & { x: number; y: number; w: number; h: number }) {
  const stars = look.stars
    ? Array.from({ length: 26 }, (_, i) => ({ cx: x + ((i * 397) % w), cy: y + ((i * 211) % (h * 0.7)), r: 1.2 + (i % 3) * 0.6 }))
    : []
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} fill={`url(#${ids.sky})`} />
      {stars.map((s, i) => (
        <circle key={i} {...s} fill="#fff" opacity={0.5 + (i % 4) * 0.12} />
      ))}
      {look.sun && <circle cx={x + w * 0.78} cy={y + h * 0.22} r={Math.min(w, h) * 0.07} fill="#fff6d8" opacity="0.9" />}
      {look.moon && (
        <g>
          <circle cx={x + w * 0.76} cy={y + h * 0.2} r={Math.min(w, h) * 0.06} fill="#f5f0dc" />
          <circle cx={x + w * 0.76 + Math.min(w, h) * 0.03} cy={y + h * 0.2 - 6} r={Math.min(w, h) * 0.055} fill={look.skyTop} />
        </g>
      )}
      {Array.from({ length: look.clouds }, (_, i) => (
        <g key={i} opacity={0.85}>
          <animateTransform attributeName="transform" type="translate" from={`${-w * 0.3} 0`} to={`${w * 1.1} 0`} dur={`${90 + i * 23}s`} begin={`${-i * 31}s`} repeatCount="indefinite" />
          <Cloud x={x + ((i * 0.37) % 1) * w * 0.4} y={y + h * (0.12 + ((i * 0.23) % 0.4))} s={0.6 + (i % 3) * 0.25} color={look.cloudColor} />
        </g>
      ))}
    </g>
  )
}

function Cloud({ x, y, s, color }: { x: number; y: number; s: number; color: string }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${s})`} fill={color}>
      <ellipse cx="0" cy="0" rx="90" ry="34" />
      <ellipse cx="-50" cy="8" rx="55" ry="26" />
      <ellipse cx="55" cy="6" rx="60" ry="28" />
      <ellipse cx="10" cy="-22" rx="50" ry="30" />
    </g>
  )
}

/** 雨・雪・霧を、指定した範囲（窓の中など）に重ねる */
function Weather({ ids, look, x, y, w, h }: Part & { x: number; y: number; w: number; h: number }) {
  return (
    <g>
      {look.rain && <rect x={x} y={y} width={w} height={h} fill={`url(#${ids.rain})`} />}
      {look.snow && <rect x={x} y={y} width={w} height={h} fill={`url(#${ids.snow})`} />}
      {look.fog && <rect x={x} y={y} width={w} height={h} fill={`url(#${ids.fog})`} />}
    </g>
  )
}

function Glow({ ids, cx, cy, r }: { ids: Ids; cx: number; cy: number; r: number }) {
  return <circle cx={cx} cy={cy} r={r} fill={`url(#${ids.glow})`} />
}

function Tint({ look }: { look: SceneLook }) {
  return <rect width="1600" height="1000" fill={look.tint} />
}

/** 窓（外の空と天気が見える） */
function Window({ ids, look, x, y, w, h, bars = true }: Part & { x: number; y: number; w: number; h: number; bars?: boolean }) {
  return (
    <g>
      <clipPath id={`${ids.win}-${x}`}>
        <rect x={x} y={y} width={w} height={h} />
      </clipPath>
      <g clipPath={`url(#${ids.win}-${x})`}>
        <SkyArea ids={ids} look={look} x={x} y={y} w={w} h={h} />
        <Weather ids={ids} look={look} x={x} y={y} w={w} h={h} />
      </g>
      <rect x={x} y={y} width={w} height={h} fill="none" stroke="#fbf4ea" strokeWidth="22" />
      {bars && (
        <g stroke="#fbf4ea" strokeWidth="12">
          <line x1={x + w / 2} y1={y} x2={x + w / 2} y2={y + h} />
          <line x1={x} y1={y + h * 0.45} x2={x + w} y2={y + h * 0.45} />
        </g>
      )}
    </g>
  )
}

function Room({ ids, look }: Part): ReactNode {
  return (
    <g>
      <rect width="1600" height="1000" fill="#efe3d3" />
      <rect y="0" width="1600" height="60" fill="#e6d7c4" />
      <Window ids={ids} look={look} x={1000} y={170} w={430} h={470} />
      {/* カーテン */}
      <path d="M950 140 q40 260 10 560 l-70 0 q30 -300 -10 -560z" fill="#e2b29b" />
      <path d="M1480 140 q-40 260 -10 560 l70 0 q-30 -300 10 -560z" fill="#e2b29b" />
      <rect x="930" y="132" width="580" height="14" rx="7" fill="#b98f72" />
      {/* 本棚 */}
      <rect x="70" y="290" width="300" height="490" rx="10" fill="#b4825c" />
      {[340, 460, 580, 700].map((sy) => (
        <rect key={sy} x="86" y={sy} width="268" height="10" fill="#93653f" />
      ))}
      {[310, 430, 550, 670].map((sy, row) =>
        [0, 1, 2, 3, 4, 5].map((i) => (
          <rect
            key={`${sy}-${i}`}
            x={100 + i * 40 + (row % 2) * 8}
            y={sy + (i % 2) * 8}
            width="30"
            height={92 - (i % 2) * 8}
            rx="4"
            fill={['#e5603f', '#6a5ae0', '#1c9a76', '#d4850f', '#4776c0', '#d24f7c'][(i + row) % 6]}
            opacity="0.8"
          />
        )),
      )}
      {/* 床 */}
      <rect y="770" width="1600" height="230" fill="#c99a6e" />
      <rect y="760" width="1600" height="14" fill="#f7efe4" />
      {[0, 1, 2, 3].map((i) => (
        <line key={i} x1="0" y1={820 + i * 50} x2="1600" y2={820 + i * 50} stroke="#b88a5f" strokeWidth="3" />
      ))}
      <ellipse cx="800" cy="900" rx="520" ry="70" fill="#e8c9b4" opacity="0.8" />
      {/* 観葉植物 */}
      <rect x="430" y="680" width="90" height="100" rx="12" fill="#d8b49a" />
      <g fill="#5f9a59">
        <ellipse cx="475" cy="620" rx="40" ry="80" transform="rotate(-20 475 620)" />
        <ellipse cx="500" cy="630" rx="36" ry="76" transform="rotate(25 500 630)" />
        <ellipse cx="460" cy="650" rx="30" ry="60" transform="rotate(-50 460 650)" />
      </g>
      {/* フロアランプ */}
      <line x1="1530" y1="430" x2="1530" y2="770" stroke="#6b5544" strokeWidth="8" />
      <path d="M1480 430 h100 l-22 -80 h-56z" fill="#f6e3c8" />
      <Tint look={look} />
      {look.lightsOn && (
        <>
          <Glow ids={ids} cx={1530} cy={400} r={260} />
          <Glow ids={ids} cx={800} cy={60} r={420} />
        </>
      )}
    </g>
  )
}

function Cafe({ ids, look }: Part): ReactNode {
  return (
    <g>
      <rect width="1600" height="1000" fill="#e9dccb" />
      {/* 大きな窓と、外の街並み */}
      <clipPath id={`${ids.win}-cafe`}>
        <rect x="100" y="110" width="1400" height="520" />
      </clipPath>
      <g clipPath={`url(#${ids.win}-cafe)`}>
        <SkyArea ids={ids} look={look} x={100} y={110} w={1400} h={520} />
        <g fill={look.lightsOn ? '#3b4256' : '#b9c3cc'} opacity="0.85">
          <rect x="140" y="400" width="160" height="230" />
          <rect x="320" y="340" width="120" height="290" />
          <rect x="980" y="380" width="200" height="250" />
          <rect x="1220" y="320" width="150" height="310" />
        </g>
        <Weather ids={ids} look={look} x={100} y={110} w={1400} h={520} />
      </g>
      <g fill="none" stroke="#5b4636" strokeWidth="16">
        <rect x="100" y="110" width="1400" height="520" />
        <line x1="450" y1="110" x2="450" y2="630" />
        <line x1="800" y1="110" x2="800" y2="630" />
        <line x1="1150" y1="110" x2="1150" y2="630" />
      </g>
      <rect y="630" width="1600" height="30" fill="#7a5a43" />
      {/* 床とカウンター */}
      <rect y="660" width="1600" height="340" fill="#a87a56" />
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <line key={i} x1="0" y1={700 + i * 55} x2="1600" y2={700 + i * 55} stroke="#956a48" strokeWidth="3" />
      ))}
      <rect x="1190" y="640" width="420" height="360" fill="#7b5139" />
      <rect x="1170" y="625" width="440" height="30" rx="6" fill="#b07b54" />
      <g fill="#fbf4ea">
        <rect x="1240" y="590" width="34" height="38" rx="6" />
        <rect x="1300" y="595" width="30" height="32" rx="6" />
      </g>
      {/* テーブルと椅子 */}
      <ellipse cx="260" cy="760" rx="120" ry="22" fill="#6e4b35" />
      <rect x="250" y="760" width="20" height="180" fill="#5d3f2c" />
      <rect x="80" y="760" width="70" height="170" rx="10" fill="#5d3f2c" opacity="0.85" />
      {/* 吊り下げの明かり */}
      {[300, 800, 1300].map((lx) => (
        <g key={lx}>
          <line x1={lx} y1="0" x2={lx} y2="70" stroke="#4a3a2e" strokeWidth="3" />
          <path d={`M${lx - 34} 100 q34 -50 68 0z`} fill="#d9a066" />
        </g>
      ))}
      <Tint look={look} />
      {[300, 800, 1300].map((lx) => (
        <Glow key={lx} ids={ids} cx={lx} cy={110} r={look.lightsOn ? 300 : 160} />
      ))}
    </g>
  )
}

function Park({ ids, look }: Part): ReactNode {
  const tree = (x: number, y: number, s: number) => (
    <g transform={`translate(${x} ${y}) scale(${s})`}>
      <rect x="-14" y="0" width="28" height="160" fill="#7b5a3e" />
      <g fill="#5f9a59">
        <circle cx="0" cy="-30" r="90" />
        <circle cx="-70" cy="20" r="65" />
        <circle cx="70" cy="20" r="65" />
      </g>
      <circle cx="-20" cy="-60" r="40" fill="#76b06c" />
    </g>
  )
  return (
    <g>
      <SkyArea ids={ids} look={look} x={0} y={0} w={1600} h={720} />
      <path d="M0 560 Q300 440 640 540 T1300 500 T1600 520 V760 H0z" fill="#9cc48f" />
      <path d="M0 640 Q400 560 820 640 T1600 610 V800 H0z" fill="#84b07a" />
      <rect y="700" width="1600" height="300" fill="#8fc27d" />
      <path d="M700 1000 L780 700 H860 L1000 1000z" fill="#e5d3b3" />
      {tree(170, 560, 1.15)}
      {tree(420, 600, 0.8)}
      {tree(1420, 560, 1.2)}
      {tree(1220, 610, 0.75)}
      {/* ベンチ */}
      <g fill="#8a6142">
        <rect x="1050" y="770" width="200" height="16" rx="4" />
        <rect x="1050" y="740" width="200" height="14" rx="4" />
        <rect x="1062" y="786" width="12" height="50" />
        <rect x="1226" y="786" width="12" height="50" />
      </g>
      {/* 花 */}
      {Array.from({ length: 18 }, (_, i) => (
        <circle key={i} cx={60 + i * 88} cy={900 + (i % 3) * 30} r="7" fill={['#f2a7b8', '#fff3a6', '#ffffff'][i % 3]} />
      ))}
      {/* 街灯 */}
      <rect x="560" y="520" width="10" height="260" fill="#4a4a4a" />
      <rect x="545" y="500" width="40" height="30" rx="6" fill="#fff4d6" />
      <Weather ids={ids} look={look} x={0} y={0} w={1600} h={1000} />
      <Tint look={look} />
      {look.lightsOn && <Glow ids={ids} cx={565} cy={515} r={200} />}
    </g>
  )
}

function Street({ ids, look }: Part): ReactNode {
  const lit = look.lightsOn
  const buildings = [
    { x: 0, w: 260, h: 520, c: '#d9c9b8' },
    { x: 250, w: 200, h: 640, c: '#c7b5a3' },
    { x: 440, w: 240, h: 470, c: '#e2d5c4' },
    { x: 960, w: 230, h: 560, c: '#cdbba8' },
    { x: 1180, w: 200, h: 680, c: '#b8a99a' },
    { x: 1370, w: 240, h: 500, c: '#ddd0bf' },
  ]
  return (
    <g>
      <SkyArea ids={ids} look={look} x={0} y={0} w={1600} h={760} />
      {/* 遠くの塔 */}
      <path d="M790 760 L815 230 L840 760z" fill={lit ? '#2e3448' : '#aab5c0'} />
      <rect x="680" y="420" width="280" height="340" fill={lit ? '#3a4055' : '#c4ced6'} />
      {buildings.map((b) => (
        <g key={b.x}>
          <rect x={b.x} y={760 - b.h} width={b.w} height={b.h} fill={b.c} />
          {Array.from({ length: Math.floor((b.h - 160) / 70) }, (_, row) =>
            Array.from({ length: Math.floor(b.w / 60) }, (_, col) => (
              <rect
                key={`${row}-${col}`}
                x={b.x + 22 + col * 60}
                y={760 - b.h + 40 + row * 70}
                width="30"
                height="40"
                rx="3"
                fill={lit ? ((row + col + b.x) % 3 === 0 ? '#5b5f6e' : '#ffd98a') : '#a9c4d6'}
              />
            )),
          )}
        </g>
      ))}
      {/* お店のひさし */}
      {[
        { x: 20, c: '#e5603f' },
        { x: 460, c: '#1c9a76' },
        { x: 1390, c: '#4776c0' },
      ].map((a) => (
        <g key={a.x}>
          <path d={`M${a.x} 640 h210 l-16 50 h-178z`} fill={a.c} />
          <rect x={a.x + 30} y="690" width="150" height="70" fill={lit ? '#ffe2a8' : '#f4ecdf'} />
        </g>
      ))}
      <rect y="760" width="1600" height="240" fill="#cfc6bb" />
      {[0, 1, 2, 3].map((i) => (
        <line key={i} x1="0" y1={800 + i * 55} x2="1600" y2={800 + i * 55} stroke="#bdb3a7" strokeWidth="3" />
      ))}
      {[300, 1300].map((lx) => (
        <g key={lx}>
          <rect x={lx} y="470" width="12" height="300" fill="#3f3f46" />
          <rect x={lx - 30} y="455" width="72" height="22" rx="8" fill="#fff4d6" />
        </g>
      ))}
      <Weather ids={ids} look={look} x={0} y={0} w={1600} h={1000} />
      <Tint look={look} />
      {lit && [306, 1306].map((lx) => <Glow key={lx} ids={ids} cx={lx} cy={470} r={220} />)}
    </g>
  )
}
