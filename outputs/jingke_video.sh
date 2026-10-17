#!/bin/bash
# 荆轲刺秦王 — 文字电影生成脚本
# 使用 FFmpeg drawtext + 转场效果

set -e

OUTPUT_DIR="/data/soffy/projects/hevi/outputs/jingke"
mkdir -p "$OUTPUT_DIR"

FONT="/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
W=1920
H=1080
FPS=30

echo "🎬 生成《荆轲刺秦王》..."

# ─── Scene 1: 开场标题 ───
echo "  Scene 1/6: 开场标题..."
ffmpeg -y -f lavfi -i "color=c=0x0a0a0a:s=${W}x${H}:d=6:r=${FPS}" \
  -vf "drawtext=fontfile=${FONT}:text='荆 轲 刺 秦 王':fontsize=96:fontcolor=0xd4af37:x=(w-text_w)/2:y=(h-text_h)/2-60:enable='between(t,0.5,5.5)':alpha='if(lt(t,1.5),t-0.5,if(gt(t,4.5),5.5-t,1))',drawtext=fontfile=${FONT}:text='— 公元前227年 —':fontsize=36:fontcolor=0x888888:x=(w-text_w)/2:y=(h+120)/2:enable='between(t,1.5,5.5)':alpha='if(lt(t,2.5),t-1.5,if(gt(t,4.5),5.5-t,1))'" \
  -c:v libx264 -pix_fmt yuv420p -preset fast "$OUTPUT_DIR/scene1.mp4" 2>/dev/null

# ─── Scene 2: 易水送别 ───
echo "  Scene 2/6: 易水送别..."
ffmpeg -y -f lavfi -i "color=c=0x1a2a1a:s=${W}x${H}:d=8:r=${FPS}" \
  -vf "drawtext=fontfile=${FONT}:text='易水送别':fontsize=72:fontcolor=0xc0d8c0:x=(w-text_w)/2:y=200:enable='between(t,0.5,7.5)':alpha='if(lt(t,1.5),t-0.5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='太子丹率百官送行至易水之畔':fontsize=32:fontcolor=0x8aaa8a:x=(w-text_w)/2:y=320:enable='between(t,2,7.5)':alpha='if(lt(t,3),t-2,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='风 萧 萧 兮 易 水 寒':fontsize=64:fontcolor=0xffffff:x=(w-text_w)/2:y=480:enable='between(t,3,7.5)':alpha='if(lt(t,4),t-3,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='壮 士 一 去 兮 不 复 还':fontsize=64:fontcolor=0xffd700:x=(w-text_w)/2:y=580:enable='between(t,4,7.5)':alpha='if(lt(t,5),t-4,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='高渐离击筑  荆轲和而歌':fontsize=28:fontcolor=0x6a8a6a:x=(w-text_w)/2:y=720:enable='between(t,5,7.5)':alpha='if(lt(t,6),t-5,if(gt(t,6.5),7.5-t,1))'" \
  -c:v libx264 -pix_fmt yuv420p -preset fast "$OUTPUT_DIR/scene2.mp4" 2>/dev/null

# ─── Scene 3: 入秦 ───
echo "  Scene 3/6: 入秦宫..."
ffmpeg -y -f lavfi -i "color=c=0x2a1a0a:s=${W}x${H}:d=7:r=${FPS}" \
  -vf "drawtext=fontfile=${FONT}:text='入 秦':fontsize=80:fontcolor=0xd4af37:x=(w-text_w)/2:y=160:enable='between(t,0.5,6.5)':alpha='if(lt(t,1.5),t-0.5,if(gt(t,5.5),6.5-t,1))',drawtext=fontfile=${FONT}:text='荆轲携督亢地图与樊於期首级':fontsize=32:fontcolor=0xaa8844:x=(w-text_w)/2:y=290:enable='between(t,1.5,6.5)':alpha='if(lt(t,2.5),t-1.5,if(gt(t,5.5),6.5-t,1))',drawtext=fontfile=${FONT}:text='以燕国使臣之名':fontsize=32:fontcolor=0xaa8844:x=(w-text_w)/2:y=340:enable='between(t,2.5,6.5)':alpha='if(lt(t,3.5),t-2.5,if(gt(t,5.5),6.5-t,1))',drawtext=fontfile=${FONT}:text='踏入咸阳宫殿':fontsize=40:fontcolor=0xffcc66:x=(w-text_w)/2:y=450:enable='between(t,3.5,6.5)':alpha='if(lt(t,4.5),t-3.5,if(gt(t,5.5),6.5-t,1))',drawtext=fontfile=${FONT}:text='秦王政 端坐龙椅之上':fontsize=32:fontcolor=0x886644:x=(w-text_w)/2:y=560:enable='between(t,4.5,6.5)':alpha='if(lt(t,5.5),t-4.5,if(gt(t,5.5),6.5-t,1))',drawtext=fontfile=${FONT}:text='文武百官  肃立两侧':fontsize=32:fontcolor=0x886644:x=(w-text_w)/2:y=620:enable='between(t,5,6.5)':alpha='if(lt(t,6),t-5,if(gt(t,5.5),6.5-t,1))'" \
  -c:v libx264 -pix_fmt yuv420p -preset fast "$OUTPUT_DIR/scene3.mp4" 2>/dev/null

# ─── Scene 4: 图穷匕见 ───
echo "  Scene 4/6: 图穷匕见..."
ffmpeg -y -f lavfi -i "color=c=0x1a0a0a:s=${W}x${H}:d=8:r=${FPS}" \
  -vf "drawtext=fontfile=${FONT}:text='图 穷 匕 见':fontsize=80:fontcolor=0xff4444:x=(w-text_w)/2:y=180:enable='between(t,0.5,7.5)':alpha='if(lt(t,1.5),t-0.5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='荆轲缓缓展开督亢地图':fontsize=36:fontcolor=0xcc8888:x=(w-text_w)/2:y=320:enable='between(t,2,7.5)':alpha='if(lt(t,3),t-2,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='图穷而匕首见':fontsize=56:fontcolor=0xffffff:x=(w-text_w)/2:y=440:enable='between(t,3.5,7.5)':alpha='if(lt(t,4.5),t-3.5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='左手把秦王之袖':fontsize=40:fontcolor=0xffcc00:x=(w-text_w)/2:y=560:enable='between(t,5,7.5)':alpha='if(lt(t,6),t-5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='右手持匕首揕之':fontsize=40:fontcolor=0xff6600:x=(w-text_w)/2:y=640:enable='between(t,5.5,7.5)':alpha='if(lt(t,6.5),t-5.5,if(gt(t,6.5),7.5-t,1))'" \
  -c:v libx264 -pix_fmt yuv420p -preset fast "$OUTPUT_DIR/scene4.mp4" 2>/dev/null

# ─── Scene 5: 逐秦王 ───
echo "  Scene 5/6: 追逐秦王..."
ffmpeg -y -f lavfi -i "color=c=0x0a0a2a:s=${W}x${H}:d=8:r=${FPS}" \
  -vf "drawtext=fontfile=${FONT}:text='逐 秦 王':fontsize=80:fontcolor=0x4488ff:x=(w-text_w)/2:y=180:enable='between(t,0.5,7.5)':alpha='if(lt(t,1.5),t-0.5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='秦王惊起  袖绝':fontsize=36:fontcolor=0x88aaff:x=(w-text_w)/2:y=310:enable='between(t,1.5,7.5)':alpha='if(lt(t,2.5),t-1.5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='拔剑  剑长  操其室':fontsize=36:fontcolor=0x88aaff:x=(w-text_w)/2:y=370:enable='between(t,2.5,7.5)':alpha='if(lt(t,3.5),t-2.5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='二人绕柱奔走':fontsize=52:fontcolor=0xffffff:x=(w-text_w)/2:y=480:enable='between(t,3.5,7.5)':alpha='if(lt(t,4.5),t-3.5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='群臣愕然  莫知所为':fontsize=32:fontcolor=0x6688aa:x=(w-text_w)/2:y=600:enable='between(t,5,7.5)':alpha='if(lt(t,6),t-5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='夏无且以药囊击荆轲':fontsize=28:fontcolor=0x556688:x=(w-text_w)/2:y=680:enable='between(t,5.5,7.5)':alpha='if(lt(t,6.5),t-5.5,if(gt(t,6.5),7.5-t,1))'" \
  -c:v libx264 -pix_fmt yuv420p -preset fast "$OUTPUT_DIR/scene5.mp4" 2>/dev/null

# ─── Scene 6: 尾声 ───
echo "  Scene 6/6: 英雄落幕..."
ffmpeg -y -f lavfi -i "color=c=0x0a0a0a:s=${W}x${H}:d=8:r=${FPS}" \
  -vf "drawtext=fontfile=${FONT}:text='英 雄 末 路':fontsize=72:fontcolor=0x888888:x=(w-text_w)/2:y=180:enable='between(t,0.5,7.5)':alpha='if(lt(t,1.5),t-0.5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='秦王拔剑斩荆轲':fontsize=36:fontcolor=0xaa6666:x=(w-text_w)/2:y=310:enable='between(t,1.5,7.5)':alpha='if(lt(t,2.5),t-1.5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='荆轲倚柱而笑':fontsize=44:fontcolor=0xffd700:x=(w-text_w)/2:y=430:enable='between(t,3,7.5)':alpha='if(lt(t,4),t-3,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='事所以不成者':fontsize=36:fontcolor=0xccccaa:x=(w-text_w)/2:y=530:enable='between(t,4,7.5)':alpha='if(lt(t,5),t-4,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='乃欲以生劫之':fontsize=36:fontcolor=0xccccaa:x=(w-text_w)/2:y=590:enable='between(t,4.5,7.5)':alpha='if(lt(t,5.5),t-4.5,if(gt(t,6.5),7.5-t,1))',drawtext=fontfile=${FONT}:text='— 太史公《史记·刺客列传》—':fontsize=24:fontcolor=0x666666:x=(w-text_w)/2:y=700:enable='between(t,5.5,7.5)':alpha='if(lt(t,6.5),t-5.5,if(gt(t,6.5),7.5-t,1))'" \
  -c:v libx264 -pix_fmt yuv420p -preset fast "$OUTPUT_DIR/scene6.mp4" 2>/dev/null

# ─── 合成全部场景 ───
echo ""
echo "🔗 合成全部场景..."

# 创建 concat 列表
cat > "$OUTPUT_DIR/concat.txt" <<EOF
file 'scene1.mp4'
file 'scene2.mp4'
file 'scene3.mp4'
file 'scene4.mp4'
file 'scene5.mp4'
file 'scene6.mp4'
EOF

ffmpeg -y -f concat -safe 0 -i "$OUTPUT_DIR/concat.txt" \
  -c:v libx264 -pix_fmt yuv420p -preset fast -crf 18 \
  "$OUTPUT_DIR/荆轲刺秦王.mp4" 2>/dev/null

echo ""
echo "✅ 完成！"
ls -lh "$OUTPUT_DIR/荆轲刺秦王.mp4"
ffprobe -v quiet -print_format json -show_format "$OUTPUT_DIR/荆轲刺秦王.mp4" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
fmt=d.get('format',{})
dur=float(fmt.get('duration',0))
size=int(fmt.get('size',0))/1024/1024
print(f'  时长: {int(dur//60)}:{int(dur%60):02d} ({dur:.1f}s)')
print(f'  大小: {size:.1f} MB')
print(f'  分辨率: 1920x1080')
"
