/**
 * VHSTape — 货架上的单盘录像带盒子(3D)
 *
 * 封面 = thumbnail(异步加载,失败/缺失用程序化封面兜底),书脊 = 程序化竖排标题。
 * hover 抬升 + 指针样式,click 上报选中。被"拿起"时(dimmed)半透明留位。
 */
'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import type { GalleryItem } from '@/types/api';
import { CATEGORY_META, SHELF } from './shelfPlan';
import { makeSpineCanvas, makeTapeCoverCanvas } from './tapeCover';
import { canvasToTexture, loadRemoteTexture } from './tapeTextures';
import { buildTapeMaterials } from './tapeMaterials';

export interface VHSTapeProps {
  item: GalleryItem;
  position: [number, number, number];
  selected: boolean;
  dimmed?: boolean;
  onSelect: (item: GalleryItem) => void;
}

export function VHSTape({ item, position, selected, dimmed = false, onSelect }: VHSTapeProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);
  const meta = CATEGORY_META[item.category in CATEGORY_META ? item.category : 'image'];

  // 封面纹理:先程序化兜底(同步可用),thumbnail 到达后替换
  const [coverTex, setCoverTex] = useState<THREE.Texture | null>(null);
  useEffect(() => {
    let alive = true;
    const fallback = canvasToTexture(
      makeTapeCoverCanvas({ title: item.title, color: meta.color, icon: meta.icon }),
    );
    setCoverTex(fallback);
    if (item.thumbnail_url) {
      void loadRemoteTexture(item.thumbnail_url).then((tex) => {
        if (!alive) {
          tex?.dispose();
          return;
        }
        if (tex) {
          setCoverTex(tex);
          fallback?.dispose();
        }
      });
    }
    return () => {
      alive = false;
      fallback?.dispose();
    };
  }, [item, meta]);

  const spineTex = useMemo(
    () => canvasToTexture(makeSpineCanvas(item.title, meta.color)),
    [item.title, meta.color],
  );

  const materials = useMemo(
    () => buildTapeMaterials(coverTex, spineTex, null),
    [coverTex, spineTex],
  );

  // hover/选中抬升动画;dimmed(被拿起)时半透明
  useFrame((_, delta) => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const targetY = position[1] + (hovered || selected ? 0.09 : 0);
    mesh.position.y = THREE.MathUtils.damp(mesh.position.y, targetY, 8, delta);
    const targetOpacity = dimmed ? 0.3 : 1;
    for (const m of mesh.material as THREE.Material[]) {
      m.transparent = targetOpacity < 1;
      if (m.opacity !== targetOpacity) m.opacity = THREE.MathUtils.damp(m.opacity, targetOpacity, 8, delta);
    }
  });

  return (
    <mesh
      ref={meshRef}
      position={position}
      material={materials}
      castShadow
      onPointerOver={(e) => {
        e.stopPropagation();
        setHovered(true);
        document.body.style.cursor = 'pointer';
      }}
      onPointerOut={() => {
        setHovered(false);
        document.body.style.cursor = 'auto';
      }}
      onClick={(e) => {
        e.stopPropagation();
        if (!dimmed) onSelect(item);
      }}
    >
      <boxGeometry args={[SHELF.BOX_W, SHELF.BOX_H, SHELF.BOX_D]} />
    </mesh>
  );
}
