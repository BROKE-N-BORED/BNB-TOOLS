"""Token math and measurements for Vision Image Optimizer.

Standard library only, except image_info, which imports Pillow
inside the function (see its docstring) so the rest of this module
stays importable without it.
"""

import math
import os

# Qwen3-VL reads images at 1 token per 32x32 px block.
TOKEN_PX = 32

SUPPORTED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff",
}


def vision_tokens(width, height):
    """Vision tokens for a picture of this size.

    tokens = ceil(w/32) * ceil(h/32). 1920x1080 reads 2040 tokens;
    512x288 reads 144.
    """
    if width < 1 or height < 1:
        raise ValueError("width and height must be at least 1")
    return math.ceil(width / TOKEN_PX) * math.ceil(height / TOKEN_PX)


def target_size(width, height, target_width):
    """Size after resizing to target_width, keeping the aspect ratio.

    target_width of None (or wider than the picture) means no resize:
    pictures are never upscaled.
    """
    if target_width is None or target_width >= width:
        return (width, height)
    if target_width < 1:
        raise ValueError("target width must be at least 1")
    new_height = max(1, round(height * target_width / width))
    return (target_width, new_height)


def clamp_crop(box, width, height):
    """Clamp a crop box (x, y, w, h) inside a picture of this size.

    Returns the clamped box, or None when the box has no overlap with
    the picture at all (a full miss is a no-op, never a crash).
    """
    if box is None:
        return None
    x, y, w, h = (int(v) for v in box)
    # Intersect with the picture: a box starting left of / above the
    # picture loses that part of its width / height, it does not
    # slide over to (0, 0) keeping its size.
    x2 = x + w
    y2 = y + h
    x = max(0, x)
    y = max(0, y)
    x2 = min(width, x2)
    y2 = min(height, y2)
    w = x2 - x
    h = y2 - y
    if w < 1 or h < 1:
        return None
    return (x, y, w, h)


def image_info(path):
    """Width, height, and file size of a picture on disk.

    Pillow is imported inside this function so the rest of this
    module stays standard library only.
    """
    from PIL import Image
    size_bytes = os.path.getsize(path)
    with Image.open(path) as img:
        return {"width": img.width, "height": img.height,
                "bytes": size_bytes}


def describe_measurements(fast_seconds, smart_seconds, tokens_before,
                          tokens_after, bytes_before, bytes_after):
    """One measurements record per describe, shown in the UI + logged."""
    return {
        "fast_seconds": fast_seconds,
        "smart_seconds": smart_seconds,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
    }


def format_measurements(measure):
    """Plain-words measurements line for the UI."""
    fast = measure.get("fast_seconds")
    smart = measure.get("smart_seconds")
    parts = []
    if fast is not None:
        parts.append("Fast look: %.2f s" % fast)
    if smart is not None:
        parts.append("Careful look: %.2f s" % smart)
    parts.append("Tokens: %d to %d"
                 % (measure["tokens_before"], measure["tokens_after"]))
    parts.append("Size: %s to %s"
                 % (human_size(measure["bytes_before"]),
                    human_size(measure["bytes_after"])))
    return "  ".join(parts)


def human_size(num_bytes):
    """1234567 -> '1.2 MB'. Plain numbers, no surprises."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return "%d B" % int(size)
            return "%.1f %s" % (size, unit)
        size /= 1024
    return "%d B" % int(num_bytes)
