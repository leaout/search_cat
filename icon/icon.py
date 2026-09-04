"""Build Search Cat PNG and Windows ICO assets from a square source image."""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def extract_colored_mark(image: Image.Image) -> Image.Image:
    """Remove a baked grayscale checkerboard while preserving enclosed whites."""
    rgb = np.asarray(image.convert('RGB'))
    channel_range = rgb.max(axis=2).astype(int) - rgb.min(axis=2).astype(int)
    dark = rgb.max(axis=2) < 165
    saturated = channel_range > 28
    seed = Image.fromarray(np.where(dark | saturated, 255, 0).astype('uint8'), 'L')
    # Remove tiny compression/color specks that can divide the checkerboard
    # into disconnected islands before determining the exterior.
    seed = seed.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))

    connectivity = seed.copy()
    width, height = connectivity.size
    for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        ImageDraw.floodfill(connectivity, point, 128, thresh=0)
    filled = np.asarray(connectivity)
    solid_alpha = np.where(filled == 128, 0, 255).astype('uint8')
    # Checkerboard pixels enclosed by the eye outline are intended white icon
    # details, not transparent background.
    enclosed_neutral = (solid_alpha == 255) & ~(dark | saturated)
    cleaned_rgb = rgb.copy()
    cleaned_rgb[enclosed_neutral] = (255, 255, 255)
    alpha = Image.fromarray(solid_alpha, 'L')
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.65))
    result = Image.fromarray(cleaned_rgb, 'RGB').convert('RGBA')
    result.putalpha(alpha)
    return result


def crop_with_margin(image: Image.Image, margin_ratio: float = 0.08) -> Image.Image:
    alpha = image.getchannel('A')
    bounds = alpha.getbbox()
    if not bounds:
        raise ValueError('源图片中没有检测到图标内容')
    cropped = image.crop(bounds)
    edge = max(cropped.size)
    margin = round(edge * margin_ratio)
    canvas_edge = edge + margin * 2
    canvas = Image.new('RGBA', (canvas_edge, canvas_edge), (0, 0, 0, 0))
    position = ((canvas_edge - cropped.width) // 2, (canvas_edge - cropped.height) // 2)
    canvas.alpha_composite(cropped, position)
    return canvas


def build(source: Path, output_png: Path, output_ico: Path, remove_checkerboard: bool) -> None:
    image = Image.open(source)
    if remove_checkerboard or image.mode != 'RGBA':
        image = extract_colored_mark(image)
    image = crop_with_margin(image).resize((1024, 1024), Image.Resampling.LANCZOS)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_png, 'PNG', optimize=True)
    image.save(output_ico, 'ICO', sizes=[(size, size) for size in ICON_SIZES])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--png', type=Path, default=Path(__file__).with_name('icon.png'))
    parser.add_argument('--ico', type=Path, default=Path(__file__).with_name('icon.ico'))
    parser.add_argument('--remove-checkerboard', action='store_true')
    args = parser.parse_args()
    build(args.source, args.png, args.ico, args.remove_checkerboard)


if __name__ == '__main__':
    main()
