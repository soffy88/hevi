/**
 * PlayerRig — 第一人称行走(3D)
 *
 * PointerLockControls 转向(点击画面锁定鼠标) + WASD/方向键移动,
 * 移动方向 = 相机朝向的水平投影;碰撞 = 货架 AABB 推回 + 店面边界 clamp。
 * 相机高度固定 1.7m(成人视高)。
 */
'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { useFrame, useThree } from '@react-three/fiber';
import { PointerLockControls } from '@react-three/drei';
import { PLAYER_RADIUS, resolvePlayerCollision, type ShelfCollider } from './playerPhysics';

export interface PlayerRigProps {
  enabled: boolean;
  colliders: ShelfCollider[];
}

export const EYE_HEIGHT = 1.7;
export const WALK_SPEED = 3.4;

export function PlayerRig({ enabled, colliders }: PlayerRigProps) {
  const { camera } = useThree();
  const keysRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!enabled) return;
    const down = (e: KeyboardEvent) => keysRef.current.add(e.code);
    const up = (e: KeyboardEvent) => keysRef.current.delete(e.code);
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
  }, [enabled]);

  useFrame((_, delta) => {
    if (!enabled) return;
    const k = keysRef.current;
    const fwd =
      (k.has('KeyW') || k.has('ArrowUp') ? 1 : 0) - (k.has('KeyS') || k.has('ArrowDown') ? 1 : 0);
    const strafe =
      (k.has('KeyD') || k.has('ArrowRight') ? 1 : 0) - (k.has('KeyA') || k.has('ArrowLeft') ? 1 : 0);
    if (fwd === 0 && strafe === 0) {
      camera.position.y = EYE_HEIGHT;
      return;
    }
    // 前进 = 相机朝向水平投影;右 = 前进 × 上
    const dir = new THREE.Vector3();
    camera.getWorldDirection(dir);
    dir.y = 0;
    dir.normalize();
    const right = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0));
    const move = dir.multiplyScalar(fwd).add(right.multiplyScalar(strafe));
    if (move.lengthSq() > 1e-6) move.normalize();
    const step = WALK_SPEED * Math.min(delta, 0.05);
    const { x, z } = resolvePlayerCollision(
      { x: camera.position.x + move.x * step, z: camera.position.z + move.z * step },
      PLAYER_RADIUS,
      colliders,
    );
    camera.position.x = x;
    camera.position.y = EYE_HEIGHT;
    camera.position.z = z;
  });

  if (!enabled) return null;
  // selector 限定只有点击 3D 画面才锁定鼠标(避免点到 DOM 按钮误触发 PointerLock)
  return <PointerLockControls pointerSpeed={0.65} selector="canvas" />;
}
