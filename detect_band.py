import sys
from hevi.layer4_legacy.quoteimage.oprim_impl.vendor_stitch import grab_frame
from PIL import ImageChops, ImageFilter
import numpy as np

def detect_band(video_path, time_t):
    frame = grab_frame(video_path, time_t)
    gray = frame.convert("L")
    # Subtitles typically have sharp edges.
    edges = ImageChops.subtract(gray, gray.filter(ImageFilter.MinFilter(3)))
    edge_data = np.array(edges)
    row_sums = edge_data.sum(axis=1)
    # usually in the bottom 40%
    h = edge_data.shape[0]
    bottom_start = int(h * 0.6)
    
    # We want to find a contiguous block with high edge density in the bottom part.
    row_sums[:bottom_start] = 0
    # smooth it
    window = int(h * 0.02)
    smoothed = np.convolve(row_sums, np.ones(window)/window, mode='same')
    
    threshold = np.max(smoothed) * 0.3
    text_rows = np.where(smoothed > threshold)[0]
    if len(text_rows) == 0:
        return 0.78, 0.96
    top = max(0, text_rows[0] - window)
    bottom = min(h, text_rows[-1] + window)
    
    # as fractions
    return top / h, bottom / h

if __name__ == '__main__':
    print(detect_band(sys.argv[1], float(sys.argv[2])))
