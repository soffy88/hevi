import re

with open("hevi/layer4_legacy/quoteimage/oprim_impl/vendor_stitch.py", "r") as f:
    content = f.read()

# We need to add a function to calculate the unified font size
unified_font_func = """
def calculate_unified_font_size(lines, base_font, font_path, max_width):
    minimum_allowed = max(12, round(base_font * 0.55))
    unified_size = base_font
    for line in lines:
        text = line["text"]
        speaker = line.get("prefix")
        label = speaker_label(speaker, text) if speaker else ""
        
        # We need to simulate the size finding for this line
        line_fit_size = minimum_allowed
        for size in range(base_font, minimum_allowed - 1, -2):
            label_width = 0
            if label:
                label_size = max(12, round(size * SPEAKER_PREFIX_SCALE))
                label_font = load_subtitle_font(font_path, label_size, label)
                label_stroke = max(2, label_size // 14)
                # use temp image to get draw
                dummy = Image.new("RGB", (1, 1))
                draw = ImageDraw.Draw(dummy)
                label_box = draw.textbbox((0, 0), label, font=label_font, stroke_width=label_stroke)
                label_width = label_box[2] - label_box[0]
            
            font = load_subtitle_font(font_path, size, text)
            stroke = max(2, size // 14)
            dummy = Image.new("RGB", (1, 1))
            draw = ImageDraw.Draw(dummy)
            candidate_box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
            
            if label_width + candidate_box[2] - candidate_box[0] <= max_width:
                line_fit_size = size
                break
        if line_fit_size < unified_size:
            unified_size = line_fit_size
    return unified_size

"""

content = content.replace("def draw_scripted_subtitle(", unified_font_func + "def draw_scripted_subtitle(")

# In draw_scripted_subtitle, we should only use font_size directly, no shrinking
draw_scripted_subtitle_old = """    chosen = None
    box = None
    for size in range(font_size, minimum - 1, -2):
        font = load_subtitle_font(font_path, size, text)
        stroke = max(2, size // 14)
        candidate_box = draw.textbbox(
            (0, 0), text, font=font, stroke_width=stroke
        )
        if label_width + candidate_box[2] - candidate_box[0] <= max_width:
            chosen = (font, stroke)
            box = candidate_box
            break
    if chosen is None:
        raise SystemExit(
            f"台词过长，缩小到可读下限后仍放不下: {text!r}；请拆句或删减"
        )"""

draw_scripted_subtitle_new = """    font = load_subtitle_font(font_path, font_size, text)
    stroke = max(2, font_size // 14)
    candidate_box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    
    if label_width + candidate_box[2] - candidate_box[0] > max_width:
        # Fallback to shrink if still too large, but shouldn't happen with unified size
        chosen = None
        for size in range(font_size, minimum - 1, -2):
            font = load_subtitle_font(font_path, size, text)
            stroke = max(2, size // 14)
            candidate_box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
            if label_width + candidate_box[2] - candidate_box[0] <= max_width:
                chosen = (font, stroke)
                box = candidate_box
                break
        if chosen is None:
            raise SystemExit(f"台词过长，缩小到可读下限后仍放不下: {text!r}；请拆句或删减")
    else:
        chosen = (font, stroke)
        box = candidate_box"""

content = content.replace(draw_scripted_subtitle_old, draw_scripted_subtitle_new)

# Now inject into scripted_render_one for layout="natural"
natural_old = """        base_font = font_size or max(16, round(strip_height * 0.62))
        draw_scripted_subtitle(
            hero, lines[0]["text"], hero.height - strip_height // 2,
            font_path, base_font, round(out_width * 0.92),
            speaker=lines[0].get("prefix"),
        )"""
natural_new = """        base_font = font_size or max(16, round(strip_height * 0.62))
        base_font = calculate_unified_font_size(lines, base_font, font_path, round(out_width * 0.92))
        draw_scripted_subtitle(
            hero, lines[0]["text"], hero.height - strip_height // 2,
            font_path, base_font, round(out_width * 0.92),
            speaker=lines[0].get("prefix"),
        )"""
content = content.replace(natural_old, natural_new)

# Inject into scripted_render_one for layout="fixed"
fixed_old = """        base_font = font_size or max(24, round(out_width / 18))

    hero = ImageOps.fit("""
fixed_new = """        base_font = font_size or max(24, round(out_width / 18))
        
    base_font = calculate_unified_font_size(lines, base_font, font_path, round(out_width * 0.92))

    hero = ImageOps.fit("""
content = content.replace(fixed_old, fixed_new)

# one more place where six-line card base font is defined
six_line_old = """        base_font = font_size or max(24, round(out_width * 0.0587))
    else:
        hero_fraction = choose_hero_fraction(strip_count, hero_fraction)
        hero_height = round(out_height * hero_fraction)"""
six_line_new = """        base_font = font_size or max(24, round(out_width * 0.0587))
    else:
        hero_fraction = choose_hero_fraction(strip_count, hero_fraction)
        hero_height = round(out_height * hero_fraction)"""
# No change needed here, we do it right before `hero = ImageOps.fit` as above

# Finally, we need to pass `base_font` exactly to all draw_scripted_subtitle in strips
# wait, for first strip in natural:
# `font_path, min(base_font, max(16, round(first_strip_height * 0.62))),`
# it's shrinking it further if first_strip_height is small!
content = re.sub(r'min\(base_font,\s*max\(16,\s*round\(first_strip_height \* 0\.62\)\)\)', 'base_font', content)
content = re.sub(r'min\(base_font,\s*max\(16,\s*round\(strip\.height \* 0\.62\)\)\)', 'base_font', content)

with open("hevi/layer4_legacy/quoteimage/oprim_impl/vendor_stitch.py", "w") as f:
    f.write(content)
