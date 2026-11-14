"""Core image work for Vision Image Optimizer: token math, resize,
compress, crop, and the hash-keyed on-disk cache.

No Qt here — pure standard library plus Pillow — so the CLI and the
tests can use all of it without a GUI.
"""

import hashlib
import io
import json
import math
import os
import shutil

from PIL import Image

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
    """Width, height, and file size of a picture on disk."""
    size_bytes = os.path.getsize(path)
    with Image.open(path) as img:
        return {"width": img.width, "height": img.height,
                "bytes": size_bytes}


def default_settings():
    """The optimize settings a fresh install starts with."""
    return {
        "width": 512,
        "quality": 85,
        "format": "JPEG",
        "crop": None,
    }


def settings_key(image_bytes, settings):
    """Cache key: sha256 of the image bytes plus the settings JSON."""
    payload = json.dumps(settings, sort_keys=True, default=str)
    digest = hashlib.sha256()
    digest.update(image_bytes)
    digest.update(b"\n")
    digest.update(payload.encode("utf-8"))
    return digest.hexdigest()


def optimize_bytes(image_bytes, settings):
    """Resize/compress/crop picture bytes. Returns a result dict.

    settings: {"width": int or None, "quality": int 1-100,
    "format": "JPEG" or "PNG", "crop": (x, y, w, h) or None}.

    The result carries the new bytes plus before/after measurements:
    width, height, tokens, file size.
    """
    fmt = str(settings.get("format", "JPEG")).upper()
    if fmt not in ("JPEG", "PNG"):
        raise ValueError("format must be JPEG or PNG")
    quality = int(settings.get("quality", 85))
    quality = max(1, min(100, quality))
    target_width = settings.get("width")

    with Image.open(io.BytesIO(image_bytes)) as img:
        orig_width, orig_height = img.width, img.height
        work = img
        crop = clamp_crop(settings.get("crop"), orig_width, orig_height)
        if crop is not None:
            x, y, w, h = crop
            work = work.crop((x, y, x + w, y + h))
        new_width, new_height = target_size(
            work.width, work.height, target_width)
        if (new_width, new_height) != (work.width, work.height):
            work = work.resize((new_width, new_height), Image.LANCZOS)
        if fmt == "JPEG" and work.mode in ("RGBA", "LA", "P"):
            work = work.convert("RGB")
        buf = io.BytesIO()
        if fmt == "JPEG":
            work.save(buf, "JPEG", quality=quality, optimize=True)
        else:
            work.save(buf, "PNG", optimize=True)
        out_bytes = buf.getvalue()

    return {
        "data": out_bytes,
        "width": new_width,
        "height": new_height,
        "tokens_before": vision_tokens(orig_width, orig_height),
        "tokens_after": vision_tokens(new_width, new_height),
        "bytes_before": len(image_bytes),
        "bytes_after": len(out_bytes),
        "format": fmt,
    }


def optimize_file(src_path, settings):
    """Optimize one file on disk. Returns the optimize_bytes result."""
    with open(src_path, "rb") as fh:
        return optimize_bytes(fh.read(), settings)


def output_path(src_path, out_dir, width, fmt):
    """Where the optimized copy goes. Never the source path itself.

    Default is a subfolder named "optimized" next to the source.
    The name carries the width so different sizes never collide.
    """
    if out_dir:
        folder = out_dir
    else:
        folder = os.path.join(os.path.dirname(os.path.abspath(src_path)),
                              "optimized")
    stem = os.path.splitext(os.path.basename(src_path))[0]
    ext = ".jpg" if fmt.upper() == "JPEG" else ".png"
    if width is None:
        name = "%s-optimized%s" % (stem, ext)
    else:
        name = "%s-%dw%s" % (stem, width, ext)
    candidate = os.path.join(folder, name)
    if os.path.abspath(candidate) == os.path.abspath(src_path):
        # Same folder and same name would overwrite the original.
        name = "%s-optimized-copy%s" % (stem, ext)
        candidate = os.path.join(folder, name)
    return candidate


def write_optimized(src_path, out_dir, settings, result=None):
    """Optimize a file and write the copy. Returns (path, result).

    Refuses to overwrite the source: if the computed output path is
    the source path, the name gains "-optimized-copy" (see
    output_path). The source file is never touched.
    """
    if result is None:
        result = optimize_file(src_path, settings)
    fmt = str(settings.get("format", "JPEG")).upper()
    dest = output_path(src_path, out_dir, settings.get("width"), fmt)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(result["data"])
    return dest, result


# ---------------------------------------------------------------- cache


class ImageCache:
    """Hash-keyed on-disk cache: same image + same settings = one answer.

    Two stores under the root dir: optimized picture bytes, and
    descriptions (with their measurements). Everything is plain
    files, so the cache survives a restart — a new process reads
    the old entries straight off disk.
    """

    def __init__(self, root, enabled=True):
        self.root = root
        self.enabled = enabled
        self.opt_dir = os.path.join(root, "optimized")
        self.desc_dir = os.path.join(root, "descriptions")
        os.makedirs(self.opt_dir, exist_ok=True)
        os.makedirs(self.desc_dir, exist_ok=True)

    # -- optimized pictures ------------------------------------------
    def get_optimized(self, image_bytes, settings):
        """Cached optimize result, or None on a miss."""
        if not self.enabled:
            return None
        key = settings_key(image_bytes, settings)
        data_path = os.path.join(self.opt_dir, key + ".bin")
        meta_path = os.path.join(self.opt_dir, key + ".json")
        if not (os.path.exists(data_path)
                and os.path.exists(meta_path)):
            return None
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
            with open(data_path, "rb") as fh:
                meta["data"] = fh.read()
        except (OSError, ValueError):
            return None
        meta["from_cache"] = True
        return meta

    def put_optimized(self, image_bytes, settings, result):
        if not self.enabled:
            return
        key = settings_key(image_bytes, settings)
        meta = {k: v for k, v in result.items() if k != "data"}
        with open(os.path.join(self.opt_dir, key + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump(meta, fh)
        with open(os.path.join(self.opt_dir, key + ".bin"), "wb") as fh:
            fh.write(result["data"])

    # -- descriptions -------------------------------------------------
    def description_key(self, optimized_bytes, prompt, fast_model,
                        smart_model):
        payload = json.dumps(
            {"prompt": prompt, "fast": fast_model, "smart": smart_model},
            sort_keys=True)
        digest = hashlib.sha256()
        digest.update(optimized_bytes)
        digest.update(b"\n")
        digest.update(payload.encode("utf-8"))
        return digest.hexdigest()

    def get_description(self, optimized_bytes, prompt, fast_model,
                        smart_model):
        if not self.enabled:
            return None
        key = self.description_key(optimized_bytes, prompt, fast_model,
                                   smart_model)
        path = os.path.join(self.desc_dir, key + ".json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            return None
        record["from_cache"] = True
        return record

    def put_description(self, optimized_bytes, prompt, fast_model,
                        smart_model, record):
        if not self.enabled:
            return
        key = self.description_key(optimized_bytes, prompt, fast_model,
                                   smart_model)
        stored = {k: v for k, v in record.items()
                  if k != "from_cache"}
        with open(os.path.join(self.desc_dir, key + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump(stored, fh)

    # -- housekeeping -------------------------------------------------
    def clear(self):
        """Empty the whole cache. Returns (files removed, bytes freed)."""
        removed = 0
        freed = 0
        for folder in (self.opt_dir, self.desc_dir):
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    freed += os.path.getsize(path)
                    os.unlink(path)
                    removed += 1
        return removed, freed

    def stats(self):
        """(optimized entries, description entries, bytes on disk)."""
        def count(folder):
            files = [n for n in os.listdir(folder)
                     if os.path.isfile(os.path.join(folder, n))]
            total = sum(os.path.getsize(os.path.join(folder, n))
                        for n in files)
            return files, total
        opt_files, opt_bytes = count(self.opt_dir)
        desc_files, desc_bytes = count(self.desc_dir)
        # Optimized entries come in pairs (.bin + .json).
        return (len(opt_files) // 2, len(desc_files),
                opt_bytes + desc_bytes)


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


def remove_tree(path):
    """Best-effort recursive delete (cache clear fallback)."""
    shutil.rmtree(path, ignore_errors=True)
