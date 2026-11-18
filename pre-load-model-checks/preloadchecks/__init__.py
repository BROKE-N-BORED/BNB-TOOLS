"""Pre-Load Model Checks: check before a model is loaded.

Before a model loads, check the machine: is there enough free
RAM for it, what is running that will fight it for RAM and CPU,
and is the model even able to do the job. If something is in
the way, a picker window lists the top few heavy processes with
checkboxes, so only the ones he picks get stopped.

The chain is small tools, each runnable alone: ram-check,
process-check, suitability-check, kill-picker, model-watchdog.
"""

__version__ = "0.1.0"
APP_NAME = "Pre-Load Model Checks"
APP_SLUG = "pre-load-model-checks"
