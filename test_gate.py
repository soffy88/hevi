from PIL import Image, ImageChops, ImageFilter, ImageStat
import sys
import numpy as np

def test_gate(img_path):
    with Image.open(img_path) as img:
        gray = img.convert("L")
        # bottom 30%
        bottom = gray.crop((0, int(gray.height * 0.7), gray.width, gray.height))
        edges = ImageChops.subtract(bottom, bottom.filter(ImageFilter.MinFilter(3)))
        stat = ImageStat.Stat(edges)
        print("Edge mean:", stat.mean[0])
        print("Edge stddev:", stat.stddev[0])
        # Also check variance of the bottom part directly
        print("Bottom stddev:", ImageStat.Stat(bottom).stddev[0])

if __name__ == '__main__':
    test_gate(sys.argv[1])
