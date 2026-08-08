/** v9.1 前端 AI 素材质检:浏览器内人脸校验(useFaceValidator)。
 *
 * 确稿台上传数字人底图时,先走本 Hook 做本地 AI 预检 —— 用
 * @vladmandic/face-api 的 TinyFaceDetector(权重位于 public/models,
 * 懒加载 + 幂等)在用户浏览器里完成:
 *   1. 文件硬性门槛:JPG/PNG 且 ≤10MB(不满足直接拒绝,不浪费模型加载);
 *   2. 恰好 1 张正脸(多人照/合照直接拒绝);
 *   3. 人脸 bbox 面积占比 ∈ [5%, 60%](半身/特写均可,远景小脸与怼脸大头照拒绝)。
 *
 * 通过后调用方才可提交给后端 POST /api/explainer/validate-presenter-image
 * 做服务端权威复核(双保险)。返回值中的 isLoading 对应用户可见文案
 * 「正在进行 AI 素材质检...」。
 */

'use client';

import { useEffect, useRef, useState } from 'react';

// face-api 在模块顶层 import 会在 jsdom/SSR 里初始化 tfjs(WebGL 探测)导致
// 测试与预渲染崩溃 —— 只在真正需要推理时动态加载(懒加载,幂等)。
type FaceApiModule = typeof import('@vladmandic/face-api');

/** 模型权重目录(public/models/tiny_face_detector/,已随仓库提交)。 */
const MODEL_URL = '/models/tiny_face_detector';

/** 与人脸占比下限 5% / 上限 60% 保持一致(见 hevi/sourcing/asset_validator.py)。 */
const MIN_FACE_RATIO = 0.05;
const MAX_FACE_RATIO = 0.6;
const MAX_FILE_BYTES = 10 * 1024 * 1024; // ≤10MB

export interface FaceValidationResult {
  /** 是否通过全部规则(文件门槛 + 单人正脸 + 占比区间)。 */
  isValid: boolean;
  /** 失败时的中文提示;通过时为 null。 */
  errorMsg: string | null;
  /** 模型正在推理 / 图片解码中。UI 展示「正在进行 AI 素材质检...」。 */
  isLoading: boolean;
  faceCount: number | null;
  faceRatio: number | null;
}

const IDLE: FaceValidationResult = {
  isValid: false,
  errorMsg: null,
  isLoading: false,
  faceCount: null,
  faceRatio: null,
};

/** 模块级单例:模型只加载一次,所有上传共用(懒加载,首次校验才下载)。 */
let modelPromise: Promise<void> | null = null;
let faceapiModule: FaceApiModule | null = null;

async function ensureFaceApi(): Promise<FaceApiModule> {
  if (!faceapiModule) {
    faceapiModule = await import('@vladmandic/face-api');
  }
  return faceapiModule;
}

async function ensureTinyFaceDetector(): Promise<FaceApiModule> {
  const faceapi = await ensureFaceApi();
  if (!modelPromise) {
    modelPromise = faceapi.nets.tinyFaceDetector
      .loadFromUri(MODEL_URL)
      .catch((reason: unknown) => {
        modelPromise = null; // 失败可重试
        throw reason;
      });
  }
  await modelPromise;
  return faceapi;
}

/** 把 File 解码为 HTMLImageElement(TinyFaceDetector 直接吃 Image)。 */
function fileToImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('图片解码失败,请换一张 JPG/PNG'));
    };
    image.src = url;
  });
}

/**
 * 校验单个图片 File。file 为 null 时回到空闲态(不触发加载)。
 * 校验是异步的:组件可用它驱动绿色/红色边框 + toast 文案。
 */
export function useFaceValidator(): {
  validate: (file: File | null) => Promise<FaceValidationResult>;
  result: FaceValidationResult;
  /** 重置为未校验态(如用户清空选择)。 */
  reset: () => void;
} {
  const [result, setResult] = useState<FaceValidationResult>(IDLE);
  const inFlight = useRef<number>(0);

  // 卸载时丢弃进行中的校验,防止 setState on unmounted。
  useEffect(() => {
    return () => {
      inFlight.current += 1;
    };
  }, []);

  async function validate(file: File | null): Promise<FaceValidationResult> {
    const ticket = ++inFlight.current;
    if (!file) {
      setResult(IDLE);
      return IDLE;
    }
    // 文件门槛:类型与大小 —— 模型都还没加载就先把脏数据挡掉。
    const isJpegPng =
      file.type === 'image/jpeg' ||
      file.type === 'image/png' ||
      /\.(jpe?g|png)$/i.test(file.name);
    if (!isJpegPng) {
      const rejected: FaceValidationResult = {
        isValid: false,
        errorMsg: '仅支持 JPG/PNG 格式的底图,请重新选择',
        isLoading: false,
        faceCount: null,
        faceRatio: null,
      };
      setResult(rejected);
      return rejected;
    }
    if (file.size > MAX_FILE_BYTES) {
      const rejected: FaceValidationResult = {
        isValid: false,
        errorMsg: `图片超过 10MB 上限(当前 ${(file.size / 1024 / 1024).toFixed(1)}MB),请压缩后重试`,
        isLoading: false,
        faceCount: null,
        faceRatio: null,
      };
      setResult(rejected);
      return rejected;
    }

    const loading: FaceValidationResult = { ...IDLE, isLoading: true };
    setResult(loading);
    try {
      const faceapi = await ensureTinyFaceDetector();
      const image = await fileToImage(file);
      const detections = await faceapi.detectAllFaces(
        image,
        new faceapi.TinyFaceDetectorOptions({ inputSize: 416, scoreThreshold: 0.5 }),
      );
      if (ticket !== inFlight.current) return result; // 已被新校验/卸载取代

      const faceCount = detections.length;
      const imgArea = image.naturalWidth * image.naturalHeight;
      let faceRatio: number | null = null;
      if (faceCount === 1 && imgArea > 0) {
        const box = detections[0].box;
        faceRatio = (box.width * box.height) / imgArea;
      }

      let errorMsg: string | null = null;
      if (faceCount === 0) {
        errorMsg = '未检测到人脸 —— 请上传正脸直视镜头的照片(禁止侧脸/低头/遮挡)';
      } else if (faceCount > 1) {
        errorMsg = `检测到 ${faceCount} 张人脸 —— 请上传单人照,避免合照干扰 AI 数字人建模`;
      } else if (faceRatio !== null && faceRatio < MIN_FACE_RATIO) {
        errorMsg = '人脸占比过小(<5%) —— 请上传半身照(人脸约占画面 50%-70%),避免全身远景';
      } else if (faceRatio !== null && faceRatio > MAX_FACE_RATIO) {
        errorMsg = '人脸占比过大(>60%) —— 请后退一点拍摄半身照,避免怼脸大头照';
      }

      const verdict: FaceValidationResult = {
        isValid: errorMsg === null,
        errorMsg,
        isLoading: false,
        faceCount,
        faceRatio,
      };
      setResult(verdict);
      return verdict;
    } catch (reason) {
      const failed: FaceValidationResult = {
        isValid: false,
        errorMsg:
          reason instanceof Error
            ? `AI 素材质检失败:${reason.message}`
            : 'AI 素材质检失败,请稍后重试',
        isLoading: false,
        faceCount: null,
        faceRatio: null,
      };
      if (ticket === inFlight.current) setResult(failed);
      return failed;
    }
  }

  function reset() {
    inFlight.current += 1;
    setResult(IDLE);
  }

  return { validate, result, reset };
}
