/**
 * StorefrontScene — 3D 店面场景(R3F Canvas)
 *
 * 1990 年代录像带租赁店氛围:暖色荧光灯、木色货架、暖灰地面。
 * 相机轨道浏览(OrbitControls,阻尼 + 角度/距离限制)。
 */
'use client';

import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import type { GalleryItem } from '@/types/api';
import { ShelfUnit } from './ShelfUnit';
import type { StoreSection } from './shelfPlan';

export interface StorefrontSceneProps {
  sections: StoreSection[];
  selectedId: string | null;
  onSelect: (item: GalleryItem) => void;
}

/** 店面外壳:地面 + 后墙 + 侧墙 + 天花灯带。 */
function StoreShell() {
  return (
    <group>
      {/* 地面 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, -2]}>
        <planeGeometry args={[26, 18]} />
        <meshStandardMaterial color="#46382b" roughness={0.96} />
      </mesh>
      {/* 后墙 */}
      <mesh position={[0, 2.6, -8.4]}>
        <boxGeometry args={[26, 5.2, 0.4]} />
        <meshStandardMaterial color="#3b2f23" roughness={0.95} />
      </mesh>
      {/* 左右侧墙 */}
      {[-1, 1].map((side) => (
        <mesh key={side} rotation={[0, Math.PI / 2, 0]} position={[side * 13, 2.6, -2]}>
          <boxGeometry args={[18, 5.2, 0.4]} />
          <meshStandardMaterial color="#33291f" roughness={0.95} />
        </mesh>
      ))}
      {/* 天花暖色光带(视觉装饰,非光源) */}
      {[-6, 0, 6].map((x) => (
        <mesh key={x} position={[x, 4.9, 2]}>
          <planeGeometry args={[3.4, 0.22]} />
          <meshStandardMaterial color="#ffd9a0" emissive="#ffcf8e" emissiveIntensity={2.2} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}

export function StorefrontScene({ sections, selectedId, onSelect }: StorefrontSceneProps) {
  return (
    <Canvas camera={{ position: [0, 3.6, 9.2], fov: 55 }} dpr={[1, 2]}>
      <color attach="background" args={['#14100c']} />
      <ambientLight intensity={0.5} color="#ffdcb8" />
      <pointLight position={[0, 5.4, 2.5]} intensity={55} color="#ffd9a0" distance={30} decay={2} />
      <pointLight position={[-7, 5.2, -1]} intensity={40} color="#ffc98a" distance={26} decay={2} />
      <pointLight position={[7, 5.2, -1]} intensity={40} color="#ffc98a" distance={26} decay={2} />
      <StoreShell />
      {sections.map((s, i) => (
        <ShelfUnit
          key={s.category}
          section={s}
          sectionIndex={i}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
      <OrbitControls
        target={[0, 1.5, -4.5]}
        enableDamping
        dampingFactor={0.08}
        minDistance={1.5}
        maxDistance={18}
        minPolarAngle={0.1}
        maxPolarAngle={1.45}
      />
    </Canvas>
  );
}
