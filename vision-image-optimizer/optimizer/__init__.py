"""Vision Image Optimizer — shrink pictures before a local vision model
looks at them, so each look costs fewer vision tokens and less time.

One window, drop images in, set your sizes, it shrinks and describes
them with the local model. Describing is optional; shrinking is not.
"""

__version__ = "0.1.0"
__app_name__ = "vision-image-optimizer"
__display_name__ = "Vision Image Optimizer"
