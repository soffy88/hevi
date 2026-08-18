/**
 * VHSTape — 货架上的单盘录像带盒子(3D)
 *
 * 六面材质:[+x 右书脊, -x 左书脊, +y 顶, -y 底, +z 封面, -z 背封]。
 * 封面 = thumbnail(异步加载,失败/缺失用程序化封面兜底),书脊 = 程序化竖排标题。
 * hover 抬升 + 指针样式,click 上报选中。
 */
'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import type { GalleryItem } from '@/types/api';
import { CATEGORY_META, SHELF } from './shelfPlan';
import { makeSpineCanvas, makeTapeCoverCanvas } from './tapeCover';
import { canvasToTexture, loadRemoteTexture } from './tapeTextures';

export interface VHSTapeProps {
  item: GalleryItem;
  position: [number, number, number];
  selected: boolean;
  onSelect: (item: GalleryItem) => void;
}

export function VHSTape({ item, position, selected, onSelect }: VHSTapeProps) {
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

  const materials = useMemo(() => {
    const body = new THREE.MeshStandardMaterial({ color: '#3b332b', roughness: 0.85 });
    const front = coverTex
      ? new THREE.MeshStandardMaterial({ map: coverTex, roughness: 0.72 })
      : body;
    const spine = spineTex
      ? new THREE.MeshStandardMaterial({ map: spineTex, roughness: 0.8 })
      : body;
    // [px 右书脊, nx 左书脊, py 顶, ny 底, pz 封面, nz 背封]
    return [spine, spine, body, body, front, body];
  }, [coverTex, spineTex]);

  // hover/选中抬升动画
  useFrame((_, delta) => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const targetY = position[1] + (hovered || selected ? 0.09 : 0);
    mesh.position.y = THREE.MathUtils.damp(mesh.position.y, targetY, 8, delta);
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
        onSelect(item);
      }}
    >
      <boxGeometry args={[SHELF.BOX_W, SHELF.BOX_H, SHELF.BOX_D]} />
    </mesh>
  );
}
