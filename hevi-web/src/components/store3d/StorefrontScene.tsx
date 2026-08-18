/**
 * StorefrontScene — 3D 店面场景(R3F Canvas)
 *
 * 模式:
 * - orbit:轨道浏览(OrbitControls,阻尼 + 角度/距离限制)
 * - walk:第一人称行走(PointerLock 转向 + WASD + 货架碰撞)
 * - 25d:2.5D 固定机位(只能横移/缩放,低功耗渲染,树莓派思路)
 *
 * 主题:暖/霓虹/琥珀/黑白,驱动墙面/地面/货架/灯光配色。
 * 选中作品被"拿起"到前台展示盒(DisplayTape),点击翻面看背封。
 */
'use client';

import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import type { GalleryItem } from '@/types/api';
import { ShelfUnit } from './ShelfUnit';
import type { StoreSection } from './shelfPlan';
import type { StoreTheme } from './storeThemes';
import { PlayerRig } from './PlayerRig';
import { DisplayTape } from './DisplayTape';
import { buildShelfColliders } from './playerPhysics';

export type StoreMode = 'orbit' | 'walk' | '25d';

export interface StorefrontSceneProps {
  sections: StoreSection[];
  selectedId: string | null;
  selectedItem: GalleryItem | null;
  facingBack: boolean;
  theme: StoreTheme;
  mode: StoreMode;
  onSelect: (item: GalleryItem) => void;
  onFlip: () => void;
}

/** 店面外壳:地面 + 后墙 + 侧墙 + 天花灯带(主题化)。 */
function StoreShell({ theme }: { theme: StoreTheme }) {
  return (
    <group>
      {/* 地面 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, -2]}>
        <planeGeometry args={[26, 18]} />
        <meshStandardMaterial color={theme.floor} roughness={0.96} />
      </mesh>
      {/* 后墙 */}
      <mesh position={[0, 2.6, -8.4]}>
        <boxGeometry args={[26, 5.2, 0.4]} />
        <meshStandardMaterial color={theme.wall} roughness={0.95} />
      </mesh>
      {/* 左右侧墙 */}
      {[-1, 1].map((side) => (
        <mesh key={side} rotation={[0, Math.PI / 2, 0]} position={[side * 13, 2.6, -2]}>
          <boxGeometry args={[18, 5.2, 0.4]} />
          <meshStandardMaterial color={theme.wall} roughness={0.95} />
        </mesh>
      ))}
      {/* 天花暖色光带(视觉装饰,非光源) */}
      {[-6, 0, 6].map((x) => (
        <mesh key={x} position={[x, 4.9, 2]}>
          <planeGeometry args={[3.4, 0.22]} />
          <meshStandardMaterial
            color={theme.accent}
            emissive={theme.accent}
            emissiveIntensity={2.2}
            toneMapped={false}
          />
        </mesh>
      ))}
    </group>
  );
}

export function StorefrontScene({
  sections,
  selectedId,
  selectedItem,
  facingBack,
  theme,
  mode,
  onSelect,
  onFlip,
}: StorefrontSceneProps) {
  const colliders = buildShelfColliders(sections);
  const lowPower = mode === '25d';

  return (
    <Canvas
      camera={{ position: [0, mode === '25d' ? 2.1 : 3.6, mode === '25d' ? 8.2 : 9.2], fov: 55 }}
      dpr={lowPower ? [1, 1] : [1, 2]}
      gl={{ antialias: !lowPower, powerPreference: lowPower ? 'low-power' : 'default' }}
    >
      <color attach="background" args={[theme.wall]} />
      <ambientLight intensity={lowPower ? 0.7 : 0.5} color={theme.ambient} />
      <pointLight
        position={[0, 5.4, 2.5]}
        intensity={lowPower ? 70 : 55}
        color={theme.light}
        distance={30}
        decay={2}
      />
      {!lowPower && (
        <>
          <pointLight position={[-7, 5.2, -1]} intensity={40} color={theme.light} distance={26} decay={2} />
          <pointLight position={[7, 5.2, -1]} intensity={40} color={theme.light} distance={26} decay={2} />
        </>
      )}
      <StoreShell theme={theme} />
      {sections.map((s, i) => (
        <ShelfUnit
          key={s.category}
          section={s}
          sectionIndex={i}
          selectedId={selectedId}
          theme={theme}
          onSelect={onSelect}
        />
      ))}
      <DisplayTape item={selectedItem} facingBack={facingBack} onFlip={onFlip} />
      {mode === 'walk' ? (
        <PlayerRig enabled colliders={colliders} />
      ) : (
        <OrbitControls
          target={mode === '25d' ? [0, 2, -5.5] : [0, 1.5, -4.5]}
          enableDamping
          dampingFactor={0.08}
          minDistance={1.5}
          maxDistance={18}
          minPolarAngle={mode === '25d' ? Math.PI / 2 - 0.06 : 0.1}
          maxPolarAngle={mode === '25d' ? Math.PI / 2 - 0.06 : 1.45}
          enableRotate={mode !== '25d'}
          enablePan={false}
        />
      )}
    </Canvas>
  );
}
