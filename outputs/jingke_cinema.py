#!/usr/bin/env python3
"""
荆轲刺秦王 - 电影级动画视频生成器
使用PIL绘制场景和角色，FFmpeg编码视频
包含：场景动画、角色动作、转场效果
"""
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math
import tempfile
import shutil

# 视频参数
WIDTH, HEIGHT, FPS = 1920, 1080, 30
OUTPUT_DIR = Path("outputs/jingke_movie")
OUTPUT_DIR.mkdir(exist_ok=True)

# 加载字体
try:
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if not Path(font_path).exists():
        font_path = "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"
    font_large = ImageFont.truetype(font_path, 80)
    font_medium = ImageFont.truetype(font_path, 48)
    font_small = ImageFont.truetype(font_path, 36)
except:
    font_large = ImageFont.load_default()
    font_medium = font_large
    font_small = font_large

# 颜色定义
DARK_BLUE = (10, 20, 40)
DARK_RED = (40, 10, 10)
GOLD = (212, 175, 55)
BLOOD_RED = (139, 0, 0)
RIVER_BLUE = (30, 50, 80)
PALACE_BROWN = (80, 50, 30)

def draw_character(draw, x, y, scale=1.0, is_warrior=True, facing_right=True):
    """绘制角色剪影"""
    s = scale
    flip = 1 if facing_right else -1
    
    # 身体
    body_color = (10, 10, 10) if is_warrior else (20, 15, 10)
    draw.ellipse([x-30*s, y-80*s, x+30*s, y+20*s], fill=body_color)
    
    # 头部
    draw.ellipse([x-20*s, y-120*s, x+20*s, y-80*s], fill=body_color)
    
    # 如果是战士，加匕首
    if is_warrior:
        dagger_x = x + 40*s*flip
        draw.polygon([
            (dagger_x, y-40*s),
            (dagger_x+15*s*flip, y-50*s),
            (dagger_x+15*s*flip, y-30*s)
        ], fill=(192, 192, 192))
    
    # 如果是秦王，加王冠
    if not is_warrior:
        crown_color = GOLD
        draw.polygon([
            (x-25*s, y-120*s),
            (x+25*s, y-120*s),
            (x+20*s, y-140*s),
            (x, y-150*s),
            (x-20*s, y-140*s)
        ], fill=crown_color)

def draw_pillar(draw, x, y, height):
    """绘制宫殿柱子"""
    draw.rectangle([x-20, y-height, x+20, y], fill=PALACE_BROWN)
    draw.rectangle([x-30, y-height-10, x+30, y-height+10], fill=(100, 70, 40))
    draw.rectangle([x-30, y, x+30, y+10], fill=(100, 70, 40))

def draw_river(draw, frame, width):
    """绘制河流波浪"""
    for i in range(10):
        wave_offset = (frame * 2 + i * 50) % width
        y = HEIGHT - 150 + i * 15
        opacity = max(0, 255 - i * 20)
        color = (*RIVER_BLUE, opacity)
        
        for j in range(0, width, 80):
            x = (j + wave_offset) % width
            draw.ellipse([x-40, y-10, x+40, y+10], fill=RIVER_BLUE)

def draw_leaves(draw, frame, count=8):
    """绘制飘落的叶子"""
    for i in range(count):
        t = (frame * 3 + i * 100) % 600
        x = (i * 200 + t * 0.5) % WIDTH
        y = t - 50
        if y < 0 or y > HEIGHT:
            continue
        
        leaf_color = (180, 120, 50) if i % 2 == 0 else (200, 140, 60)
        angle = math.sin(t * 0.05) * 30
        size = 15
        
        # 简单的叶子形状
        draw.ellipse([x-size, y-size//2, x+size, y+size//2], fill=leaf_color)

def draw_map_scroll(draw, x, y, width, height, progress):
    """绘制展开的地图"""
    # 卷轴主体
    draw.rectangle([x, y, x+width, y+height], fill=(180, 160, 130))
    
    # 卷轴两端
    draw.ellipse([x-10, y-5, x+10, y+height+5], fill=(120, 80, 50))
    draw.ellipse([x+width-10, y-5, x+width+10, y+height+5], fill=(120, 80, 50))
    
    # 地图纹理（根据展开进度）
    if progress > 0.3:
        for i in range(int(width * progress / 40)):
            ix = x + 20 + i * 40
            draw.ellipse([ix, y+30, ix+20, y+50], fill=(140, 120, 90))
            draw.line([ix, y+60, ix+30, y+80], fill=(140, 120, 90), width=2)

def draw_text_with_shadow(draw, text, x, y, font, color, shadow_offset=3):
    """绘制带阴影的文字"""
    shadow_color = (0, 0, 0)
    draw.text((x+shadow_offset, y+shadow_offset), text, font=font, fill=shadow_color)
    draw.text((x, y), text, font=font, fill=color)

def ease_in_out(t):
    """缓入缓出"""
    return t * t * (3 - 2 * t)

def fade_transition(frame, start, duration, fade_in=30, fade_out=30):
    """淡入淡出转场"""
    if frame < start:
        return 0
    if frame < start + fade_in:
        return (frame - start) / fade_in
    if frame > start + duration - fade_out:
        return (start + duration - frame) / fade_out
    if frame <= start + duration:
        return 1
    return 0

# 场景1: 易水送别 (8秒 = 240帧)
def scene_farewell(frame):
    img = Image.new('RGB', (WIDTH, HEIGHT), DARK_BLUE)
    draw = ImageDraw.Draw(img, 'RGBA')
    
    # 渐变天空
    for y in range(HEIGHT // 2):
        alpha = y / (HEIGHT // 2)
        color = (
            int(DARK_BLUE[0] * (1 - alpha) + 30 * alpha),
            int(DARK_BLUE[1] * (1 - alpha) + 40 * alpha),
            int(DARK_BLUE[2] * (1 - alpha) + 60 * alpha)
        )
        draw.line([(0, y), (WIDTH, y)], fill=color)
    
    # 河流
    draw_river(draw, frame, WIDTH)
    
    # 飘叶
    draw_leaves(draw, frame, 12)
    
    # 角色入场动画
    progress = min(1.0, frame / 60)
    eased = ease_in_out(progress)
    char_x = -200 + eased * (WIDTH * 0.35 + 200)
    draw_character(draw, int(char_x), HEIGHT - 350, scale=1.5, is_warrior=True)
    
    # 送别人群（静态剪影）
    for i in range(5):
        x = WIDTH * 0.6 + i * 80
        draw_character(draw, x, HEIGHT - 300, scale=0.8, is_warrior=False)
    
    # 文字淡入
    text_alpha = fade_transition(frame, 60, 180, 30, 30)
    if text_alpha > 0:
        img_with_text = img.copy()
        text_draw = ImageDraw.Draw(img_with_text, 'RGBA')
        
        title = "易水送别"
        bbox = text_draw.textbbox((0, 0), title, font=font_large)
        tw = bbox[2] - bbox[0]
        draw_text_with_shadow(text_draw, title, (WIDTH-tw)//2, 150, font_large, (*GOLD, int(255*text_alpha)))
        
        subtitle1 = "风萧萧兮易水寒"
        bbox1 = text_draw.textbbox((0, 0), subtitle1, font=font_medium)
        tw1 = bbox1[2] - bbox1[0]
        draw_text_with_shadow(text_draw, subtitle1, (WIDTH-tw1)//2, 280, font_medium, (255, 255, 255, int(255*text_alpha)))
        
        subtitle2 = "壮士一去兮不复还"
        bbox2 = text_draw.textbbox((0, 0), subtitle2, font=font_medium)
        tw2 = bbox2[2] - bbox2[0]
        draw_text_with_shadow(text_draw, subtitle2, (WIDTH-tw2)//2, 350, font_medium, (255, 215, 0, int(255*text_alpha)))
        
        return img_with_text
    
    return img

# 场景2: 入秦宫 (8秒 = 240帧)
def scene_enter_palace(frame):
    img = Image.new('RGB', (WIDTH, HEIGHT), (40, 20, 10))
    draw = ImageDraw.Draw(img, 'RGBA')
    
    # 宫殿背景
    for i in range(7):
        x = 200 + i * 250
        draw_pillar(draw, x, HEIGHT - 100, 600)
    
    # 荆轲入场动画
    progress = min(1.0, frame / 120)
    eased = ease_in_out(progress)
    char_y = HEIGHT - 200 + eased * (-150)
    char_scale = 0.6 + eased * 0.4
    draw_character(draw, WIDTH // 2, int(char_y), scale=char_scale, is_warrior=True)
    
    # 文字
    text_alpha = fade_transition(frame, 30, 180, 30, 30)
    if text_alpha > 0:
        img_with_text = img.copy()
        text_draw = ImageDraw.Draw(img_with_text, 'RGBA')
        
        title = "入秦宫"
        bbox = text_draw.textbbox((0, 0), title, font=font_large)
        tw = bbox[2] - bbox[0]
        draw_text_with_shadow(text_draw, title, (WIDTH-tw)//2, 100, font_large, (*GOLD, int(255*text_alpha)))
        
        subtitle = "携督亢地图与樊於期首级"
        bbox1 = text_draw.textbbox((0, 0), subtitle, font=font_small)
        tw1 = bbox1[2] - bbox1[0]
        draw_text_with_shadow(text_draw, subtitle, (WIDTH-tw1)//2, 220, font_small, (170, 136, 68, int(255*text_alpha)))
        
        return img_with_text
    
    return img

# 场景3: 图穷匕见 (8秒 = 240帧)
def scene_dagger_revealed(frame):
    # 背景从深棕渐变到血红
    progress = min(1.0, frame / 120)
    bg_r = int(40 + progress * 60)
    bg_g = int(20 - progress * 10)
    bg_b = int(10 - progress * 5)
    img = Image.new('RGB', (WIDTH, HEIGHT), (bg_r, bg_g, bg_b))
    draw = ImageDraw.Draw(img, 'RGBA')
    
    # 地图展开动画
    map_width = int(progress * 800)
    map_x = (WIDTH - map_width) // 2
    draw_map_scroll(draw, map_x, HEIGHT//2 - 100, map_width, 200, progress)
    
    # 匕首闪现（地图展开后）
    if progress > 0.7:
        dagger_alpha = min(1.0, (progress - 0.7) / 0.3)
        dagger_x = map_x + map_width - 50
        dagger_y = HEIGHT // 2
        
        # 匕首
        draw.polygon([
            (dagger_x, dagger_y-60),
            (dagger_x+20, dagger_y-80),
            (dagger_x+20, dagger_y-40)
        ], fill=(192, 192, 192, int(255*dagger_alpha)))
        draw.rectangle([dagger_x-5, dagger_y-40, dagger_x+5, dagger_y], fill=(80, 50, 30, int(255*dagger_alpha)))
        
        # 红色闪光
        if progress > 0.8:
            flash = Image.new('RGBA', (WIDTH, HEIGHT), (255, 0, 0, int(80 * (progress - 0.8) / 0.2)))
            img = Image.alpha_composite(img.convert('RGBA'), flash).convert('RGB')
            draw = ImageDraw.Draw(img, 'RGBA')
    
    # 文字
    text_alpha = fade_transition(frame, 90, 120, 30, 30)
    if text_alpha > 0:
        img_with_text = img.copy()
        text_draw = ImageDraw.Draw(img_with_text, 'RGBA')
        
        title = "图穷匕见"
        bbox = text_draw.textbbox((0, 0), title, font=font_large)
        tw = bbox[2] - bbox[0]
        title_color = (255, 68, 68) if progress > 0.7 else GOLD
        draw_text_with_shadow(text_draw, title, (WIDTH-tw)//2, 80, font_large, (*title_color, int(255*text_alpha)))
        
        if progress > 0.8:
            subtitle1 = "左手把秦王之袖"
            bbox1 = text_draw.textbbox((0, 0), subtitle1, font=font_small)
            tw1 = bbox1[2] - bbox1[0]
            draw_text_with_shadow(text_draw, subtitle1, (WIDTH-tw1)//2, HEIGHT-200, font_small, (255, 255, 255, int(255*text_alpha)))
            
            subtitle2 = "右手持匕首揕之"
            bbox2 = text_draw.textbbox((0, 0), subtitle2, font=font_small)
            tw2 = bbox2[2] - bbox2[0]
            draw_text_with_shadow(text_draw, subtitle2, (WIDTH-tw2)//2, HEIGHT-150, font_small, (255, 102, 0, int(255*text_alpha)))
        
        return img_with_text
    
    return img

# 场景4: 逐秦王 (8秒 = 240帧)
def scene_chase(frame):
    img = Image.new('RGB', (WIDTH, HEIGHT), (10, 10, 30))
    draw = ImageDraw.Draw(img, 'RGBA')
    
    # 中央柱子
    draw_pillar(draw, WIDTH//2, HEIGHT//2, 400)
    
    # 追逐动画
    angle = frame * 5
    radius = 200
    cx, cy = WIDTH//2, HEIGHT//2
    
    # 荆轲
    jk_x = int(cx + radius * math.cos(math.radians(angle)))
    jk_y = int(cy + radius * 0.5 * math.sin(math.radians(angle)))
    draw_character(draw, jk_x, jk_y, scale=1.2, is_warrior=True, facing_right=math.cos(math.radians(angle)) > 0)
    
    # 秦王（对面）
    qw_x = int(cx + radius * math.cos(math.radians(angle + 180)))
    qw_y = int(cy + radius * 0.5 * math.sin(math.radians(angle + 180)))
    draw_character(draw, qw_x, qw_y, scale=1.3, is_warrior=False, facing_right=math.cos(math.radians(angle + 180)) > 0)
    
    # 文字
    text_alpha = fade_transition(frame, 30, 180, 30, 30)
    if text_alpha > 0:
        img_with_text = img.copy()
        text_draw = ImageDraw.Draw(img_with_text, 'RGBA')
        
        title = "逐秦王"
        bbox = text_draw.textbbox((0, 0), title, font=font_large)
        tw = bbox[2] - bbox[0]
        draw_text_with_shadow(text_draw, title, (WIDTH-tw)//2, 80, font_large, (68, 136, 255, int(255*text_alpha)))
        
        subtitle = "二人绕柱而走"
        bbox1 = text_draw.textbbox((0, 0), subtitle, font=font_medium)
        tw1 = bbox1[2] - bbox1[0]
        draw_text_with_shadow(text_draw, subtitle, (WIDTH-tw1)//2, 200, font_medium, (136, 170, 255, int(255*text_alpha)))
        
        if frame > 120:
            extra = "群臣愕然 莫知所为"
            bbox2 = text_draw.textbbox((0, 0), extra, font=font_small)
            tw2 = bbox2[2] - bbox2[0]
            draw_text_with_shadow(text_draw, extra, (WIDTH-tw2)//2, HEIGHT-120, font_small, (255, 255, 255, int(255*text_alpha)))
        
        return img_with_text
    
    return img

# 场景5: 英雄落幕 (10秒 = 300帧)
def scene_finale(frame):
    # 背景渐暗
    darkness = min(1.0, frame / 200)
    bg_val = int(20 * (1 - darkness * 0.7))
    img = Image.new('RGB', (WIDTH, HEIGHT), (bg_val, bg_val, bg_val))
    draw = ImageDraw.Draw(img, 'RGBA')
    
    # 荆轲靠柱（从站立到跪倒）
    progress = min(1.0, frame / 180)
    char_y = int(HEIGHT - 300 + progress * 50)
    char_scale = 1.2 - progress * 0.2
    draw_character(draw, WIDTH//2, char_y, scale=char_scale, is_warrior=True)
    
    # 血迹
    if progress > 0.3:
        blood_alpha = min(1.0, (progress - 0.3) / 0.3)
        draw.ellipse([WIDTH//2-80, char_y+30, WIDTH//2+80, char_y+50], 
                     fill=(139, 0, 0, int(180*blood_alpha)))
    
    # 文字序列
    img_with_text = img.copy()
    text_draw = ImageDraw.Draw(img_with_text, 'RGBA')
    
    # 标题
    title_alpha = fade_transition(frame, 30, 240, 30, 30)
    if title_alpha > 0:
        title = "英雄落幕"
        bbox = text_draw.textbbox((0, 0), title, font=font_large)
        tw = bbox[2] - bbox[0]
        draw_text_with_shadow(text_draw, title, (WIDTH-tw)//2, 80, font_large, (136, 136, 136, int(255*title_alpha)))
    
    # 荆轲台词
    quote_alpha = fade_transition(frame, 90, 150, 30, 30)
    if quote_alpha > 0:
        quote1 = "事所以不成者"
        bbox1 = text_draw.textbbox((0, 0), quote1, font=font_medium)
        tw1 = bbox1[2] - bbox1[0]
        draw_text_with_shadow(text_draw, quote1, (WIDTH-tw1)//2, HEIGHT-250, font_medium, (255, 215, 0, int(255*quote_alpha)))
        
        quote2 = "乃欲以生劫之"
        bbox2 = text_draw.textbbox((0, 0), quote2, font=font_medium)
        tw2 = bbox2[2] - bbox2[0]
        draw_text_with_shadow(text_draw, quote2, (WIDTH-tw2)//2, HEIGHT-190, font_medium, (255, 215, 0, int(255*quote_alpha)))
    
    # 出处
    source_alpha = fade_transition(frame, 150, 120, 30, 30)
    if source_alpha > 0:
        source = "— 太史公《史记·刺客列传》—"
        bbox3 = text_draw.textbbox((0, 0), source, font=font_small)
        tw3 = bbox3[2] - bbox3[0]
        draw_text_with_shadow(text_draw, source, (WIDTH-tw3)//2, HEIGHT-100, font_small, (102, 102, 102, int(255*source_alpha)))
    
    # THE END
    end_alpha = fade_transition(frame, 210, 90, 30, 30)
    if end_alpha > 0:
        end_text = "THE END"
        bbox4 = text_draw.textbbox((0, 0), end_text, font=font_medium)
        tw4 = bbox4[2] - bbox4[0]
        draw_text_with_shadow(text_draw, end_text, (WIDTH-tw4)//2, HEIGHT-50, font_medium, (68, 68, 68, int(255*end_alpha)))
    
    return img_with_text

# 转场：淡入淡出
def transition_fade(frame1, frame2, progress):
    return Image.blend(frame1, frame2, progress)

def main():
    print("🎬 生成《荆轲刺秦王》电影级动画视频...")
    print(f"   分辨率: {WIDTH}x{HEIGHT}  FPS: {FPS}")
    
    # 创建临时帧目录
    temp_dir = tempfile.mkdtemp()
    frame_count = 0
    
    try:
        scenes = [
            (scene_farewell, 240, "易水送别"),
            (scene_enter_palace, 240, "入秦宫"),
            (scene_dagger_revealed, 240, "图穷匕见"),
            (scene_chase, 240, "逐秦王"),
            (scene_finale, 300, "英雄落幕"),
        ]
        
        total_frames = sum(d for _, d, _ in scenes)
        print(f"   总帧数: {total_frames} ({total_frames/FPS:.1f}秒)")
        
        # 生成所有帧
        for scene_func, duration, scene_name in scenes:
            print(f"\n🎬 场景: {scene_name} ({duration}帧, {duration/FPS:.1f}秒)")
            
            for i in range(duration):
                frame = scene_func(i)
                frame_path = Path(temp_dir) / f"frame_{frame_count:05d}.png"
                frame.save(frame_path, "PNG")
                frame_count += 1
                
                if (i + 1) % 30 == 0:
                    print(f"   进度: {i+1}/{duration} ({(i+1)/duration*100:.0f}%)")
        
        print(f"\n✅ 渲染完成: {frame_count}帧")
        
        # FFmpeg编码
        output_path = OUTPUT_DIR / "jingke_cinema.mp4"
        print(f"\n🎥 编码视频: {output_path}")
        
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", f"{temp_dir}/frame_%05d.png",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path)
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        # 验证输出
        if output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            print(f"\n✅ 视频生成成功!")
            print(f"   文件: {output_path}")
            print(f"   大小: {size_mb:.2f} MB")
            print(f"   时长: {frame_count/FPS:.1f}秒")
            print(f"   分辨率: {WIDTH}x{HEIGHT}")
            print(f"   FPS: {FPS}")
        else:
            print("❌ 视频文件未生成")
    
    finally:
        # 清理临时文件
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    main()
