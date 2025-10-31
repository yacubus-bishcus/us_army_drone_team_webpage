#scripts/vector_file_converter.py
from PIL import Image
import numpy as np
import io, cv2, svgwrite, argparse

# Convert raster PNG to SVG by edge detection and path tracing
"""
Usage:
python -m scripts.vector_file_converter --input_path INPUT_PATH --output_path OUTPUT_PATH
"""

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert raster PNG to SVG by edge detection and path tracing."
        )
    )
    parser.add_argument(
        "--input_path",
        type=str,
        dest="input_path"
        default=None,
        help="Provide the PNG input path",
    )
    parser.add_argument(
        "--output_path",
        type=str,
        dest="output_svg_path",
        default=None,
        help="Provide output path"
    )

    return parser.parse_args()

def main():
    args = parse_args()
    if args.input_path or args.output_path == None:
        print("Input Path or Output path required. See documentation.")
        return 
    # Load the image
    image = Image.open(args.input_path).convert("L")
    img_array = np.array(image)

    # Edge detection
    edges = cv2.Canny(img_array, 100, 200)

    # Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Create SVG drawing
    height, width = img_array.shape
    dwg = svgwrite.Drawing(args.output_svg_path, profile='tiny', size=(width, height))

    for contour in contours:
        points = [(int(p[0][0]), int(p[0][1])) for p in contour]
        dwg.add(dwg.polyline(points=points, stroke='black', fill='none', stroke_width=1))

    # Save SVG file
    dwg.save()

    args.output_svg_path
    return 

if __name__ == "__main__":
    main()