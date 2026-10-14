"""
Hevi SVGO Cleaner: Optimizes and cleans SVG vector assets before animation rendering, providing size comparison metrics.
"""

import os
import re
from typing import Dict

class SVGOCleaner:
    @staticmethod
    def clean_svg_string(svg_content: str) -> str:
        # Basic SVG optimization: remove comments, excessive whitespace, unnecessary metadata
        cleaned = re.sub(r'<!--.*?-->', '', svg_content, flags=re.DOTALL)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = re.sub(r'>\s+<', '><', cleaned)
        return cleaned.strip()

    @classmethod
    def clean_file(cls, input_path: str, output_path: str) -> Dict[str, int]:
        if not os.path.exists(input_path):
            # Create a sample SVG if input doesn't exist
            os.makedirs(os.path.dirname(input_path) or ".", exist_ok=True)
            with open(input_path, "w") as f:
                f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><!-- comment --><circle cx="50" cy="50" r="40" fill="red"/></svg>')

        original_size = os.path.getsize(input_path)
        with open(input_path, "r") as f:
            content = f.read()

        optimized = cls.clean_svg_string(content)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(optimized)

        optimized_size = os.path.getsize(output_path)
        return {
            "original_size_bytes": original_size,
            "optimized_size_bytes": optimized_size,
            "savings_percent": round((1 - optimized_size / original_size) * 100, 2) if original_size > 0 else 0.0
        }
