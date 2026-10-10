import sys
import numpy as np
from PIL import ImageChops, ImageFilter
from hevi.layer4_legacy.quoteimage.oprim_impl.vendor_stitch import grab_frame

def detect_subtitle_band(video_path, times):
    top_min, bottom_max = 1.0, 0.0
    for t in times:
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
            
    if top_min < bottom_max:
        return top_min, bottom_max
    return 0.78, 0.96

if __name__ == '__main__':
    print(detect_subtitle_band(sys.argv[1], [float(sys.argv[2])]))
