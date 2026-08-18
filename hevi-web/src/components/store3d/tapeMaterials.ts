/**
 * tapeMaterials — 录像带六面材质构建(纯函数)
 *
 * 六面顺序(BoxGeometry 约定):[+x 右书脊, -x 左书脊, +y 顶, -y 底, +z 封面, -z 背封]。
 * 货架盒与展示盒共用;封面/书脊/背封任一缺失时回退纯色材质。
 */
import * as THREE from 'three';

export function buildTapeMaterials(
  coverTex: THREE.Texture | null,
  spineTex: THREE.Texture | null,
  backTex: THREE.Texture | null,
): THREE.Material[] {
  const body = new THREE.MeshStandardMaterial({ color: '#3b332b', roughness: 0.85 });
  const front = coverTex
    ? new THREE.MeshStandardMaterial({ map: coverTex, roughness: 0.72 })
    : body;
  const spine = spineTex
    ? new THREE.MeshStandardMaterial({ map: spineTex, roughness: 0.8 })
    : body;
  const back = backTex
    ? new THREE.MeshStandardMaterial({ map: backTex, roughness: 0.78 })
    : body;
  return [spine, spine, body, body, front, back];
}
