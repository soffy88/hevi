import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export const Finale: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();

  // 荆轲靠柱 (从站立到跪倒)
  const personY = interpolate(frame, [0, 120], [height - 300, height - 250], {
    extrapolateRight: 'clamp',
  });
  const personScale = interpolate(frame, [0, 120], [1.0, 0.9], {
    extrapolateRight: 'clamp',
  });

  // 背景渐暗
  const bgDarkness = interpolate(frame, [0, 150], [0, 0.3], {
    extrapolateRight: 'clamp',
  });

  // 文字淡入
  const titleOpacity = spring({frame: frame - 20, fps, config: {damping: 20}});
  const quoteOpacity = spring({frame: frame - 80, fps, config: {damping: 20}});
  const endOpacity = spring({frame: frame - 140, fps, config: {damping: 20}});

  return (
    <AbsoluteFill style={{
      background: `linear-gradient(180deg, 
        rgba(10, 10, 10, ${1 - bgDarkness}) 0%, 
        rgba(20, 10, 10, ${1 - bgDarkness}) 50%, 
        rgba(5, 5, 5, 1) 100%)`,
    }}>
      {/* 荆轲剪影 */}
      <svg width={width} height={height} style={{position: 'absolute'}}>
        <g transform={`translate(${width / 2}, ${personY}) scale(${personScale})`}>
          {/* 身体 */}
          <ellipse cx={0} cy={0} rx={40} ry={80} fill="#0a0a0a" />
          {/* 头 */}
          <circle cx={0} cy={-110} r={28} fill="#0a0a0a" />
          {/* 靠柱 */}
          <rect x={-10} y={-150} width={20} height={300} fill="#2a1a0a" opacity={0.5} />
          {/* 血迹 */}
          <ellipse cx={0} cy={50} rx={60} ry={10} fill="#8a0a0a" opacity={0.6} />
        </g>
      </svg>

      {/* 标题 */}
      <div style={{
        position: 'absolute',
        top: 100,
        width: '100%',
        textAlign: 'center',
        opacity: titleOpacity,
      }}>
        <div style={{
          fontSize: 72,
          fontWeight: 'bold',
          color: '#888888',
          textShadow: '0 0 20px rgba(136, 136, 136, 0.5)',
        }}>
          英雄落幕
        </div>
      </div>

      {/* 荆轲台词 */}
      <div style={{
        position: 'absolute',
        bottom: 300,
        width: '100%',
        textAlign: 'center',
        opacity: quoteOpacity,
      }}>
        <div style={{
          fontSize: 44,
          color: '#ffd700',
          textShadow: '0 0 15px rgba(255, 215, 0, 0.5)',
          fontStyle: 'italic',
        }}>
          "事所以不成者
        </div>
        <div style={{
          fontSize: 44,
          color: '#ffd700',
          marginTop: 15,
          textShadow: '0 0 15px rgba(255, 215, 0, 0.5)',
          fontStyle: 'italic',
        }}>
          乃欲以生劫之"
        </div>
      </div>

      {/* 出处 */}
      <div style={{
        position: 'absolute',
        bottom: 200,
        width: '100%',
        textAlign: 'center',
        opacity: quoteOpacity,
      }}>
        <div style={{
          fontSize: 28,
          color: '#666666',
        }}>
          — 太史公《史记 · 刺客列传》—
        </div>
      </div>

      {/* THE END */}
      <div style={{
        position: 'absolute',
        bottom: 100,
        width: '100%',
        textAlign: 'center',
        opacity: endOpacity,
      }}>
        <div style={{
          fontSize: 48,
          color: '#444444',
          letterSpacing: 10,
        }}>
          THE END
        </div>
      </div>
    </AbsoluteFill>
  );
};
