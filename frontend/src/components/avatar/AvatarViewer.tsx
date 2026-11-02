import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { VRMLoaderPlugin, VRMUtils, type VRM } from '@pixiv/three-vrm'
import type { Emotion } from '../../lib/emotion'

export type Activity = 'idle' | 'listening' | 'thinking' | 'speaking'

export interface AvatarViewerProps {
  url: string
  /** 口パク用の音量（0〜1）を返す関数。毎フレーム呼ばれる */
  getLevel?: () => number
  emotion?: Emotion
  activity?: Activity
  className?: string
}

const EMOTIONS: Exclude<Emotion, 'neutral'>[] = ['happy', 'sad', 'surprised', 'relaxed', 'angry']
const EMOTION_HOLD_SECONDS = 6

function hasWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  } catch {
    return false
  }
}

/** VRM アバターの表示。まばたき・呼吸・表情・口パク・会話中のリアクションを行う。 */
export default function AvatarViewer({ url, getLevel, emotion = 'neutral', activity = 'idle', className }: AvatarViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [message, setMessage] = useState('')
  // 再読み込みせずに最新の値を描画ループへ渡すための参照
  const live = useRef({ getLevel, emotion, activity, emotionSince: 0 })
  live.current.getLevel = getLevel
  live.current.activity = activity
  if (live.current.emotion !== emotion) {
    live.current.emotion = emotion
    live.current.emotionSince = performance.now() / 1000
  }

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    if (!hasWebGL()) {
      setStatus('error')
      setMessage('この環境では3D表示（WebGL）が使えません。')
      return
    }
    setStatus('loading')
    let disposed = false
    let frame = 0
    let vrm: VRM | null = null

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    container.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 20)
    camera.position.set(0, 1.35, 1.6)
    const target = new THREE.Vector3(0, 1.3, 0)
    camera.lookAt(target)
    // VRM の MToon は明るさに敏感なため、控えめな光量にする
    const light = new THREE.DirectionalLight(0xffffff, 1.6)
    light.position.set(0.5, 1.5, 1.5)
    scene.add(light, new THREE.AmbientLight(0xffffff, 0.4))
    // 視線の先（カメラ付近）。考え中は少し上を見る
    const gaze = new THREE.Object3D()
    scene.add(gaze)

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = container
      if (!w || !h) return
      renderer.setSize(w, h, false)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(container)
    resize()

    const loader = new GLTFLoader()
    loader.register((parser) => new VRMLoaderPlugin(parser))
    loader.load(
      url,
      (gltf) => {
        if (disposed) return
        const loaded = gltf.userData.vrm as VRM | undefined
        if (!loaded) {
          setStatus('error')
          setMessage('VRMとして読み込めませんでした。')
          return
        }
        VRMUtils.removeUnnecessaryVertices(gltf.scene)
        // combineSkeletons は一部のモデル（Seed-san 等）で腕の変形が崩れたため使わない
        VRMUtils.rotateVRM0(loaded)
        loaded.scene.traverse((obj) => (obj.frustumCulled = false))
        scene.add(loaded.scene)
        vrm = loaded
        // 腕を下ろした自然な姿勢にする（VRM は T ポーズで読み込まれる）
        const humanoid = loaded.humanoid
        humanoid.getNormalizedBoneNode('leftUpperArm')?.rotation.set(0, 0, -1.2)
        humanoid.getNormalizedBoneNode('rightUpperArm')?.rotation.set(0, 0, 1.2)
        humanoid.getNormalizedBoneNode('leftLowerArm')?.rotation.set(0, 0, -0.15)
        humanoid.getNormalizedBoneNode('rightLowerArm')?.rotation.set(0, 0, 0.15)
        if (loaded.lookAt) loaded.lookAt.target = gaze
        // 顔の高さに合わせてカメラを配置する（モデルの身長差に対応）
        loaded.update(0)
        const head = humanoid.getNormalizedBoneNode('head')
        if (head) {
          const headPos = head.getWorldPosition(new THREE.Vector3())
          target.set(0, headPos.y - 0.12, 0)
          camera.position.set(0, headPos.y - 0.05, headPos.y * 1.05)
          camera.lookAt(target)
        }
        gaze.position.copy(camera.position)
        setStatus('ready')
      },
      undefined,
      () => {
        if (disposed) return
        setStatus('error')
        setMessage('アバターを読み込めませんでした。ファイルが壊れていないか確認してください。')
      },
    )

    const clock = new THREE.Clock()
    let nextBlink = 2 + Math.random() * 3
    let blinkStart = -1
    let mouth = 0
    const expressionValues: Record<string, number> = {}

    const animate = () => {
      frame = requestAnimationFrame(animate)
      const delta = Math.min(clock.getDelta(), 0.1)
      const t = clock.elapsedTime
      if (vrm) {
        const { getLevel: level, activity: act, emotion: emo, emotionSince } = live.current
        const em = vrm.expressionManager
        const humanoid = vrm.humanoid

        // まばたき（ランダム間隔）
        if (blinkStart < 0 && t > nextBlink) blinkStart = t
        let blink = 0
        if (blinkStart >= 0) {
          const p = (t - blinkStart) / 0.16
          blink = p < 0.5 ? p * 2 : Math.max(0, 2 - p * 2)
          if (p >= 1) {
            blinkStart = -1
            nextBlink = t + 2 + Math.random() * 4
          }
        }

        // 口パク（音量を平滑化）
        const targetMouth = act === 'speaking' && level ? Math.min(1, level() * 1.6) : 0
        mouth += (targetMouth - mouth) * Math.min(1, delta * 18)

        // 表情（一定時間で自然に戻す）。話し中は少し弱める
        const active = emo !== 'neutral' && performance.now() / 1000 - emotionSince < EMOTION_HOLD_SECONDS ? emo : 'neutral'
        for (const name of EMOTIONS) {
          const goal = name === active ? (act === 'speaking' ? 0.6 : 0.85) : act === 'thinking' && name === 'relaxed' ? 0.3 : 0
          const value = expressionValues[name] ?? 0
          expressionValues[name] = value + (goal - value) * Math.min(1, delta * 4)
          em?.setValue(name, expressionValues[name])
        }
        em?.setValue('blink', blink)
        em?.setValue('aa', mouth)

        // 待機モーション（呼吸・頭の揺れ）と会話中のリアクション
        const breath = Math.sin(t * 1.6) * 0.02
        const chest = humanoid.getNormalizedBoneNode('chest') ?? humanoid.getNormalizedBoneNode('spine')
        chest?.rotation.set(breath, 0, 0)
        const head = humanoid.getNormalizedBoneNode('head')
        if (head) {
          let pitch = Math.sin(t * 0.7) * 0.03
          let roll = Math.sin(t * 0.5) * 0.03
          if (act === 'listening') {
            pitch += 0.08 + Math.sin(t * 3) * 0.02 // 少しうなずくように聞く
          } else if (act === 'thinking') {
            pitch -= 0.06
            roll += 0.12 // 首をかしげる
          } else if (act === 'speaking') {
            pitch += mouth * 0.05
          }
          head.rotation.set(pitch, Math.sin(t * 0.4) * 0.05, roll)
        }
        gaze.position.set(camera.position.x, camera.position.y + (act === 'thinking' ? 0.5 : 0), camera.position.z)
        vrm.update(delta)
      }
      renderer.render(scene, camera)
    }
    animate()

    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      observer.disconnect()
      if (vrm) VRMUtils.deepDispose(vrm.scene)
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [url])

  return (
    <div className={`avatar-viewer ${className ?? ''}`} ref={containerRef}>
      {status === 'loading' && <div className="avatar-overlay">アバターを読み込み中…</div>}
      {status === 'error' && (
        <div className="avatar-overlay error-text" role="alert">
          {message}
        </div>
      )}
    </div>
  )
}
