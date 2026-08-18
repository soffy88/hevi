/**
 * DisplayTape — 前台展示盒:选中后被"拿起"到柜台,点击翻面看背封
 *
 * 位置固定在前台柜台(z≈4.4,相机默认前方);翻面 rotation.y 缓动 0 ↔ π。
 * 背封 = 程序化画布(标题/描述/出品条),封面 = thumbnail 或程序化兜底。
 */
'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import type { GalleryItem } from '@/types/api';
import { CATEGORY_META, SHELF } from './shelfPlan';
import { makeBackCoverCanvas, makeSpineCanvas, makeTapeCoverCanvas } from './tapeCover';
import { canvasToTexture, loadRemoteTexture } from './tapeTextures';
import { buildTapeMaterials } from './tapeMaterials';

export interface DisplayTapeProps {
  item: GalleryItem | null;
  facingBack: boolean;
  onFlip: () => void;
}

/** 柜台展示位(世界坐标)。 */
export const DISPLAY_POS: [number, number, number] = [0, 1.18, 4.4];

export function DisplayTape({ item, facingBack, onFlip }: DisplayTapeProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);
  const meta = item ? CATEGORY_META[item.category in CATEGORY_META ? item.category : 'image'] : null;

  const [coverTex, setCoverTex] = useState<THREE.Texture | null>(null);
  useEffect(() => {
    if (!item) {
      setCoverTex(null);
      return;
    }
    let alive = true;
    const fallback = canvasToTexture(
      makeTapeCoverCanvas({ title: item.title, color: meta!.color, icon: meta!.icon }),
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
    () =>
      item
        ? canvasToTexture(makeSpineCanvas(item.title, meta!.color))
        : null,
    [item, meta],
  );

  const backTex = useMemo(
    () =>
      item
        ? canvasToTexture(
            makeBackCoverCanvas({
              title: item.title,
              description: item.description,
              prompt: item.prompt,
              color: meta!.color,
              icon: meta!.icon,
            }),
          )
        : null,
    [item, meta],
  );

  const materials = useMemo(
    () => (item ? buildTapeMaterials(coverTex, spineTex, backTex) : null),
    [item, coverTex, spineTex, backTex],
  );

  useFrame((_, delta) => {
    const mesh = meshRef.current;
    if (!mesh || !item) return;
    // 入场:从镜头前方低位缓动到柜台
    mesh.position.x = THREE.MathUtils.damp(mesh.position.x, DISPLAY_POS[0], 6, delta);
    mesh.position.y = THREE.MathUtils.damp(mesh.position.y, DISPLAY_POS[1], 6, delta);
    mesh.position.z = THREE.MathUtils.damp(mesh.position.z, DISPLAY_POS[2], 6, delta);
    // 翻面
    const targetY = facingBack ? Math.PI : 0;
    mesh.rotation.y = THREE.MathUtils.damp(mesh.rotation.y, targetY, 7, delta);
  });

  if (!item || !materials) return null;

  return (
    <group>
      {/* 柜台 */}
      <mesh position={[0, 0.62, 4.4]}>
        <boxGeometry args={[2.2, 0.12, 0.7]} />
        <meshStandardMaterial color="#4a3a28" roughness={0.9} />
      </mesh>
      <mesh position={[0, 0.3, 4.4]}>
        <boxGeometry args={[1.9, 0.5, 0.5]} />
        <meshStandardMaterial color="#3b2e20" roughness={0.92} />
      </mesh>
      <mesh
        ref={meshRef}
        position={[DISPLAY_POS[0] - 1.6, DISPLAY_POS[1] - 0.9, DISPLAY_POS[2]]}
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
          onFlip();
        }}
      >
        <boxGeometry args={[SHELF.BOX_W, SHELF.BOX_H, SHELF.BOX_D]} />
      </mesh>
      {/* 翻面提示条 */}
      <mesh position={[0, DISPLAY_POS[1] - 0.85, 4.4]}>
        <planeGeometry args={[1.6, 0.3]} />
        <meshStandardMaterial
          color={hovered ? '#ffe9c4' : '#c9b896'}
          transparent
          opacity={0.9}
          roughness={0.8}
        />
      </mesh>
    </group>
  );
}
