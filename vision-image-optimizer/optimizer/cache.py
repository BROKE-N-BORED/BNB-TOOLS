"""Hash-keyed on-disk cache for Vision Image Optimizer.

Standard library only. Two stores under the root dir: optimized
picture bytes, and descriptions (with their measurements).
Everything is plain files, so the cache survives a restart.
"""

import hashlib
import json
import os
import shutil


def settings_key(image_bytes, settings):
    """Cache key: sha256 of the image bytes plus the settings JSON."""
    payload = json.dumps(settings, sort_keys=True, default=str)
    digest = hashlib.sha256()
    digest.update(image_bytes)
    digest.update(b"\n")
    digest.update(payload.encode("utf-8"))
    return digest.hexdigest()


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


def remove_tree(path):
    """Best-effort recursive delete (cache clear fallback)."""
    shutil.rmtree(path, ignore_errors=True)
