import re
with open("hevi/layer4_legacy/quoteimage/omodul_impl/produce.py", "r") as f:
    content = f.read()

new_logic = """
    aligner = WhisperAligner()
    sentences = aligner.transcribe_segments(str(video_path))
    
    if strategy == "auto":
        picked = pick_sentences(sentences, count=4)
    elif strategy == "time_range":
        start_time = float(kwargs.get("start_time", 0))
        end_time = float(kwargs.get("end_time", 999999))
        picked = [s for s in sentences if start_time <= s["t"] <= end_time]
        if len(picked) > 6:
            picked = picked[:6]
    else:
        return {"status": "failed", "error": "Unknown strategy and no fallback allowed."}
        
    if not picked:
        return {"status": "failed", "error": "No sentences picked."}
"""

old_logic = """    # Run ASR if auto strategy
    sentences = []
    if strategy == "auto":
        aligner = WhisperAligner()
        sentences = aligner.transcribe_segments(str(video_path))
        picked = pick_sentences(sentences, count=4)
    else:
        # For 'manual' strategy or time range, we would use kwargs
        # For simplicity, fallback to a dummy if no sentences provided
        picked = [{"t": 5.0, "text": "第一句台词"}, {"t": 10.0, "text": "第二句台词"}]
        
    if not picked:
        return {"status": "failed", "error": "No sentences picked."}"""

content = content.replace(old_logic, new_logic.strip())

band_logic = """
def detect_subtitle_band(video_path, times):
    import numpy as np
    from PIL import ImageChops, ImageFilter
    from hevi.layer4_legacy.quoteimage.oprim_impl.vendor_stitch import grab_frame
    
    top_min, bottom_max = 1.0, 0.0
    for t in times:
        try:
            frame = grab_frame(str(video_path), t)
            gray = frame.convert("L")
            edges = ImageChops.subtract(gray, gray.filter(ImageFilter.MinFilter(3)))
            edge_data = np.array(edges)
            row_sums = edge_data.sum(axis=1)
            
            h = edge_data.shape[0]
            bottom_start = int(h * 0.5)
            row_sums[:bottom_start] = 0
            
            window = max(1, int(h * 0.02))
            smoothed = np.convolve(row_sums, np.ones(window)/window, mode='same')
            
            threshold = np.max(smoothed) * 0.3
            text_rows = np.where(smoothed > threshold)[0]
            if len(text_rows) > 0:
                top = max(0, text_rows[0] - window) / h
                bottom = min(h, text_rows[-1] + window) / h
                top = max(0.0, top - 0.02)
                bottom = min(1.0, bottom + 0.02)
                top_min = min(top_min, top)
                bottom_max = max(bottom_max, bottom)
        except Exception:
            pass
            
    if top_min < bottom_max:
        return top_min, bottom_max
    return 0.78, 0.96

def produce_quote_image("""

content = content.replace("def produce_quote_image(", band_logic)

args_logic = """        band_top = kwargs.get("band_top")
        band_bottom = kwargs.get("band_bottom")
        if band_top is None or band_bottom is None:
            band_top, band_bottom = detect_subtitle_band(video_path, [s["t"] for s in picked])
            
        args = argparse.Namespace(
            video=str(video_path),
            manifest=str(manifest_path),
            out_dir=str(output_dir),
            band_top=band_top,
            band_bottom=band_bottom,"""

old_args_logic = """        args = argparse.Namespace(
            video=str(video_path),
            manifest=str(manifest_path),
            out_dir=str(output_dir),
            band_top=kwargs.get("band_top", 0.78),
            band_bottom=kwargs.get("band_bottom", 0.96),"""

content = content.replace(old_args_logic, args_logic)

with open("hevi/layer4_legacy/quoteimage/omodul_impl/produce.py", "w") as f:
    f.write(content)
