/**
 * tapeTextures — three.js 纹理工具(canvas → 纹理 / 失败降级)
 *
 * 与 tapeCover.ts(纯逻辑)分离:本模块依赖 three,只在 3D 场景中消费。
 */
import * as THREE from 'three';

/** canvas → CanvasTexture(sRGB);canvas 为空(null,jsdom/无 2D 环境)返回 null。 */
export function canvasToTexture(canvas: HTMLCanvasElement | null): THREE.CanvasTexture | null {
  if (!canvas) return null;
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

/** 加载远程缩略图纹理;失败 resolve(null),调用方保留程序化兜底。 */
export function loadRemoteTexture(url: string): Promise<THREE.Texture | null> {
  return new Promise((resolve) => {
    const loader = new THREE.TextureLoader();
    loader.load(
      url,
      (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = 4;
        resolve(tex);
      },
      undefined,
      () => resolve(null),
    );
  });
}
