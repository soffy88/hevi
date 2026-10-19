import React from 'react';
import { AbsoluteFill, Audio, Img, interpolate, useCurrentFrame } from 'remotion';
import { Video } from '@remotion/media';

export type MotionLayer = {
  id: string;
  type: 'text' | 'image' | 'video' | 'background';
  text?: string;
  src?: string;
  color?: string;
  x?: number;
  y?: number;
  fontSize?: number;
  start_frame: number;
  end_frame: number;
  animation?: 'fade' | 'translate' | 'scale';
  scene?: 'title' | 'lower-third' | 'image-text' | 'intro' | 'outro' | 'quote' | 'chapter';
};

export type MotionSpec = {
  composition_id: string;
  width: number;
  height: number;
  fps: number;
  duration_frames: number;
  layers: MotionLayer[];
};

export type MotionGraphicsProps = {
  spec: MotionSpec;
  audio_src?: string;
};

function animatedStyle(layer: MotionLayer, frame: number): React.CSSProperties {
  const local = Math.max(0, frame - layer.start_frame);
  const span = Math.max(1, layer.end_frame - layer.start_frame);
  const progress = interpolate(local, [0, Math.min(15, span)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = layer.animation === 'fade' || !layer.animation ? progress : 1;
  // Keep the visual alive after its entrance: the old implementation clamped
  // every transform after 15 frames, leaving 6-8 second scenes effectively frozen.
  const ambient = Math.sin((local / span) * Math.PI * 2);
  const translate = (layer.animation === 'translate' ? (1 - progress) * 48 : 0) + ambient * 7;
  const scale = layer.animation === 'scale' ? 0.86 + progress * 0.14 + ambient * 0.045 : 1;
  return {
    opacity,
    transform: `translateY(${translate}px) scale(${scale})`,
    position: 'absolute',
    left: `${layer.x ?? 50}%`,
    top: `${layer.y ?? 50}%`,
    transformOrigin: 'center center',
  };
}

export const MotionGraphics: React.FC<MotionGraphicsProps> = ({ spec, audio_src }) => {
  const frame = useCurrentFrame();
  const active = spec.layers.filter(
    (layer) => frame >= layer.start_frame && frame < layer.end_frame,
  );
  const backgrounds = active.filter((layer) => layer.type === 'background');
  const foreground = active.filter((layer) => layer.type !== 'background');
  return (
    <AbsoluteFill style={{ backgroundColor: '#101827', fontFamily: 'Arial, sans-serif' }}>
      {audio_src && <Audio src={audio_src} />}
      {backgrounds.map((layer) => {
        // Three slow ambient sweeps per clip are visible at 64x64 quality-analysis
        // resolution; a one-time 15-frame fade was effectively static for the rest.
        const progress = 0.5 + 0.5 * Math.sin((frame / Math.max(1, spec.duration_frames - 1)) * Math.PI * 6);
        const position = `${Math.round(progress * 100)}% ${Math.round(50 + Math.sin(progress * Math.PI * 2) * 18)}%`;
        const base = layer.color ?? '#101827';
        return (
          <AbsoluteFill
            key={layer.id}
            style={{
              backgroundColor: base,
              backgroundImage: `radial-gradient(ellipse at ${position}, rgba(46, 126, 176, 0.72), transparent 58%), linear-gradient(135deg, ${base}, #142b40 58%, #0b1220)`,
              backgroundSize: '240% 240%, 100% 100%',
              backgroundPosition: `${position}, center`,
            }}
          />
        );
      })}
      {foreground.map((layer) => {
        const style = animatedStyle(layer, frame);
        if (layer.type === 'image' && layer.src) {
          return <Img key={layer.id} src={layer.src} style={{ ...style, width: '72%', height: '52%', objectFit: 'contain', transform: `${style.transform} translate(-50%, -50%)` }} />;
        }
        if (layer.type === 'video' && layer.src) {
          return <Video key={layer.id} src={layer.src} objectFit="contain" style={{ ...style, width: '72%', height: '52%', transform: `${style.transform} translate(-50%, -50%)` }} />;
        }
        return (
          <div
            key={layer.id}
            style={{
              ...style,
              transform: `${style.transform} translate(-50%, -50%)`,
              width: '88%',
              color: layer.color ?? '#f8fafc',
              fontSize: layer.fontSize ?? 52,
              fontWeight: layer.scene === 'lower-third' ? 600 : 800,
              textAlign: 'center',
              whiteSpace: 'pre-wrap',
            }}
          >
            {layer.text ?? ''}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};


export const getMotionDuration = (props: MotionGraphicsProps): number =>
  Math.max(1, Math.round(props.spec.duration_frames));
