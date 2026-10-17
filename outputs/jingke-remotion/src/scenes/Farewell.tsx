import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export const Farewell: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();

  // 背景河流动画
  const waveOffset = frame * 2;

  // 人物入场 (从左侧滑入)
  const personX = interpolate(frame, [0, 40], [-200, width * 0.3], {
    extrapolateRight: 'clamp',
    extrapolateLeft: 'clamp',
  });

  // 落叶动画
  const leaves = Array.from({length: 8}, (_, i) => ({
    x: (i * 240 + frame * 3) % width,
    y: (i * 150 + frame * 4) % height,
    rotation: frame * 5 + i * 45,
    size: 20 + (i % 3) * 10,
  }));

  // 文字淡入
  const titleOpacity = spring({frame: frame - 60, fps, config: {damping: 20}});
  const subtitleOpacity = spring({frame: frame - 90, fps, config: {damping: 20}});

  return (
    <AbsoluteFill style={{
      background: 'linear-gradient(180deg, #1a2a3a 0%, #2a3a4a 50%, #3a4a5a 100%)',
    }}>
      {/* 河流 */}
      <svg width={width} height={height} style={{position: 'absolute', bottom: 0}}>
        <defs>
          <linearGradient id="water" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#4a6a8a" />
            <stop offset="50%" stopColor="#5a7a9a" />
            <stop offset="100%" stopColor="#4a6a8a" />
          </linearGradient>
        </defs>
        {Array.from({length: 5}, (_, i) => (
          <ellipse
            key={i}
            cx={(waveOffset + i * 400) % (width + 400) - 200}
            cy={height - 100 + i * 20}
            rx={300}
            ry={80}
            fill="url(#water)"
            opacity={0.3}
          />
        ))}
      </svg>

      {/* 人物剪影 */}
      <svg width={width} height={height} style={{position: 'absolute'}}>
        <g transform={`translate(${personX}, ${height - 350})`}>
          {/* 身体 */}
          <ellipse cx={0} cy={0} rx={40} ry={80} fill="#0a0a0a" />
          {/* 头 */}
          <circle cx={0} cy={-120} r={30} fill="#0a0a0a" />
          {/* 帽子 */}
          <rect x={-40} y={-160} width={80} height={20} fill="#0a0a0a" />
          <rect x={-20} y={-180} width={40} height={30} fill="#0a0a0a" />
        </g>
      </svg>

      {/* 落叶 */}
      {leaves.map((leaf, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: leaf.x,
            top: leaf.y,
            width: leaf.size,
            height: leaf.size,
            background: i % 2 === 0 ? '#d4a574' : '#c49564',
            borderRadius: '50% 0 50% 0',
            transform: `rotate(${leaf.rotation}deg)`,
            opacity: 0.7,
          }}
        />
      ))}

      {/* 标题 */}
      <div style={{
        position: 'absolute',
        top: 200,
        width: '100%',
        textAlign: 'center',
        opacity: titleOpacity,
      }}>
        <div style={{
          fontSize: 80,
          fontWeight: 'bold',
          color: '#d4af37',
          textShadow: '0 0 20px rgba(212, 175, 55, 0.5)',
        }}>
          易水送别
        </div>
      </div>

      {/* 诗句 */}
      <div style={{
        position: 'absolute',
        bottom: 250,
        width: '100%',
        textAlign: 'center',
        opacity: subtitleOpacity,
      }}>
        <div style={{
          fontSize: 48,
          color: '#ffffff',
          textShadow: '0 0 10px rgba(255, 255, 255, 0.3)',
        }}>
          风萧萧兮易水寒
        </div>
        <div style={{
          fontSize: 48,
          color: '#ffd700',
          marginTop: 20,
          textShadow: '0 0 10px rgba(255, 215, 0, 0.3)',
        }}>
          壮士一去兮不复还
        </div>
      </div>
    </AbsoluteFill>
  );
};
