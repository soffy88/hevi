import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export const DaggerRevealed: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();

  // 地图展开动画
  const mapWidth = interpolate(frame, [20, 80], [100, 800], {
    extrapolateRight: 'clamp',
    extrapolateLeft: 'clamp',
  });

  // 匕首闪现 (地图展开后)
  const daggerOpacity = interpolate(frame, [85, 90], [0, 1], {
    extrapolateRight: 'clamp',
    extrapolateLeft: 'clamp',
  });
  const daggerScale = spring({frame: frame - 85, fps, config: {stiffness: 200, damping: 10}});

  // 红色闪烁
  const redFlash = interpolate(frame, [90, 100, 110], [0, 1, 0], {
    extrapolateRight: 'clamp',
    extrapolateLeft: 'clamp',
  });

  const titleOpacity = spring({frame: frame - 10, fps, config: {damping: 20}});

  return (
    <AbsoluteFill style={{
      background: `linear-gradient(180deg, 
        ${frame > 85 ? '#3a0a0a' : '#1a0a0a'} 0%, 
        ${frame > 85 ? '#5a1a1a' : '#2a0a0a'} 100%)`,
      transition: 'background 0.3s',
    }}>
      {/* 红色闪烁效果 */}
      <div style={{
        position: 'absolute',
        width: '100%',
        height: '100%',
        background: `rgba(255, 0, 0, ${redFlash * 0.3})`,
        pointerEvents: 'none',
      }} />

      {/* 地图 */}
      <svg width={width} height={height} style={{position: 'absolute'}}>
        <defs>
          <linearGradient id="mapGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#d4b896" />
            <stop offset="100%" stopColor="#a8876a" />
          </linearGradient>
        </defs>
        {/* 地图卷轴 */}
        <rect
          x={(width - mapWidth) / 2}
          y={height / 2 - 150}
          width={mapWidth}
          height={300}
          fill="url(#mapGrad)"
          stroke="#8a6a4a"
          strokeWidth={3}
        />
        {/* 地图纹理 */}
        {mapWidth > 200 && (
          <>
            <circle cx={width / 2 - 100} cy={height / 2 - 50} r={20} fill="#6a4a2a" opacity={0.3} />
            <circle cx={width / 2 + 100} cy={height / 2 + 50} r={25} fill="#6a4a2a" opacity={0.3} />
            <path d={`M${width / 2 - 150} ${height / 2} L${width / 2 + 150} ${height / 2 - 30}`} stroke="#6a4a2a" strokeWidth={2} opacity={0.4} />
          </>
        )}
      </svg>

      {/* 匕首 */}
      {frame > 85 && (
        <svg width={width} height={height} style={{position: 'absolute'}}>
          <g
            transform={`translate(${width / 2 + 200}, ${height / 2}) scale(${daggerScale})`}
            opacity={daggerOpacity}
          >
            {/* 刀刃 */}
            <polygon
              points="-5,-80 5,-80 8,0 -8,0"
              fill="#c0c0c0"
              stroke="#808080"
              strokeWidth={2}
            />
            {/* 刀柄 */}
            <rect x={-10} y={0} width={20} height={40} fill="#4a3a2a" />
            {/* 刀柄装饰 */}
            <circle cx={0} cy={20} r={8} fill="#d4af37" />
          </g>
        </svg>
      )}

      {/* 标题 */}
      <div style={{
        position: 'absolute',
        top: 100,
        width: '100%',
        textAlign: 'center',
        opacity: titleOpacity,
      }}>
        <div style={{
          fontSize: 80,
          fontWeight: 'bold',
          color: frame > 85 ? '#ff4444' : '#d4af37',
          textShadow: frame > 85
            ? '0 0 30px rgba(255, 68, 68, 0.8)'
            : '0 0 20px rgba(212, 175, 55, 0.5)',
          transition: 'all 0.3s',
        }}>
          图穷匕见
        </div>
      </div>

      {/* 描述文字 */}
      {frame > 100 && (
        <div style={{
          position: 'absolute',
          bottom: 150,
          width: '100%',
          textAlign: 'center',
          opacity: spring({frame: frame - 100, fps}),
        }}>
          <div style={{
            fontSize: 48,
            color: '#ffffff',
            textShadow: '0 0 15px rgba(255, 255, 255, 0.5)',
          }}>
            左手把秦王之袖
          </div>
          <div style={{
            fontSize: 48,
            color: '#ff6600',
            marginTop: 20,
            textShadow: '0 0 15px rgba(255, 102, 0, 0.5)',
          }}>
            右手持匕首揕之
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
};
