/**
 * ShelfUnit — 一段货架(分区)(3D)
 *
 * 结构:背板 + 双侧柱 + 3 层搁板 + 顶板 + 顶部挂式分区标牌。
 * 盒子按 layoutTapes(纯函数)落位,局部坐标原点 = 货架段中心(地面)。
 */
'use client';

import { useMemo } from 'react';
import * as THREE from 'three';
import type { GalleryItem } from '@/types/api';
import { SHELF, layoutTapes, sectionCenterX, type StoreSection } from './shelfPlan';
import { VHSTape } from './VHSTape';
import { canvasToTexture } from './tapeTextures';
import { makeSignCanvas } from './tapeCover';
import type { StoreTheme } from './storeThemes';

export interface ShelfUnitProps {
  section: StoreSection;
  sectionIndex: number;
  selectedId: string | null;
  theme: StoreTheme;
  onSelect: (item: GalleryItem) => void;
}

export function ShelfUnit({ section, sectionIndex, selectedId, theme, onSelect }: ShelfUnitProps) {
  const tapes = layoutTapes(section);
  const signTex = useMemo(
    () =>
      canvasToTexture(
        makeSignCanvas({ label: section.label, icon: section.icon, color: section.color }),
      ),
    [section.label, section.icon, section.color],
  );

  return (
    <group position={[sectionCenterX(sectionIndex), 0, -5.5]}>
      {/* 背板 */}
      <mesh position={[0, SHELF.SECTION_H / 2, -SHELF.SECTION_D / 2]}>
        <boxGeometry args={[SHELF.SECTION_W, SHELF.SECTION_H, 0.06]} />
        <meshStandardMaterial color={theme.woodDark} roughness={0.92} />
      </mesh>
      {/* 双侧柱 */}
      {[-1, 1].map((side) => (
        <mesh key={side} position={[side * (SHELF.SECTION_W / 2 - 0.03), SHELF.SECTION_H / 2, 0]}>
          <boxGeometry args={[0.06, SHELF.SECTION_H, SHELF.SECTION_D]} />
          <meshStandardMaterial color={theme.wood} roughness={0.85} />
        </mesh>
      ))}
      {/* 搁板 */}
      {SHELF.SHELF_YS.map((y) => (
        <mesh key={y} position={[0, y, 0]}>
          <boxGeometry args={[SHELF.SECTION_W, 0.05, SHELF.SECTION_D]} />
          <meshStandardMaterial color={theme.wood} roughness={0.85} />
        </mesh>
      ))}
      {/* 顶板 */}
      <mesh position={[0, SHELF.SECTION_H + 0.025, 0]}>
        <boxGeometry args={[SHELF.SECTION_W, 0.05, SHELF.SECTION_D]} />
        <meshStandardMaterial color={theme.wood} roughness={0.85} />
      </mesh>
      {/* 分区标牌 */}
      {signTex && (
        <mesh position={[0, SHELF.SECTION_H + 0.32, 0.06]}>
          <planeGeometry args={[1.7, 0.42]} />
          <meshStandardMaterial map={signTex} roughness={0.6} side={THREE.DoubleSide} />
        </mesh>
      )}
      {/* 录像带盒子 */}
      {tapes.map(({ item, position }) => (
        <VHSTape
          key={item.item_id}
          item={item}
          position={position}
          selected={selectedId === item.item_id}
          dimmed={selectedId === item.item_id}
          onSelect={onSelect}
        />
      ))}
    </group>
  );
}
