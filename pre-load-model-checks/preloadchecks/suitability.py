"""Suitability check: can this model do this job.

A model card says what the model can do (its capabilities, its
context length, its size). Task requirements say what the job
needs. When the model cannot do the job, say so BEFORE loading
it: never load a model that will run a while and do nothing.

Model card JSON:
  {"name": "example-7b", "size_gb": 4.5,
   "capabilities": ["chat", "code"],
   "context_tokens": 32768}

Task requirements JSON:
  {"needs_capabilities": ["code"],
   "min_context_tokens": 8192, "max_size_gb": 6}

Any field may be left out; a missing field is simply not
checked. When the card says nothing about capabilities at all,
the check warns that it cannot prove the model fits the task.
"""

import json

from . import ram as ram_mod


class BadInput(ValueError):
    """The card or the task file is not usable JSON."""


def load_json_file(path, what):
    """Load a JSON file, raising BadInput in plain words."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise BadInput("cannot read the %s file %s (%s)"
                       % (what, path, exc.strerror or exc))
    except ValueError:
        raise BadInput("the %s file %s is not valid JSON"
                       % (what, path))
    if not isinstance(data, dict):
        raise BadInput("the %s file %s must hold one JSON object"
                       % (what, path))
    return data


def _as_number(value, field, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BadInput("the %s %r must be a number" % (what, field))
    return value


def check_suitability(card, task, available_bytes=None):
    """Compare a model card with task requirements.

    Returns (suitable, problems, warnings): suitable is False
    when any problem blocks the job. Warnings do not block.
    With available_bytes, the model size is also checked
    against free RAM (the ram-check verdict, in one place).
    """
    problems = []
    warnings = []
    name = card.get("name") or "this model"

    needs = task.get("needs_capabilities") or []
    if not isinstance(needs, list):
        raise BadInput("task needs_capabilities must be a list")
    capabilities = card.get("capabilities")
    if capabilities is None:
        if needs:
            warnings.append(
                "The model card does not say what %s can do, so "
                "this check cannot prove it fits the task." % name)
    elif not isinstance(capabilities, list):
        raise BadInput("model card capabilities must be a list")
    else:
        have = set(str(c).lower() for c in capabilities)
        for need in needs:
            if str(need).lower() not in have:
                problems.append(
                    "%s cannot do %s, and the task needs it."
                    % (name, need))

    min_context = task.get("min_context_tokens")
    if min_context is not None:
        min_context = _as_number(min_context, "min_context_tokens",
                                 "task")
        context = card.get("context_tokens")
        if context is None:
            warnings.append(
                "The model card does not say how much context %s "
                "holds, so the %d-token requirement could not be "
                "checked." % (name, min_context))
        else:
            context = _as_number(context, "context_tokens",
                                 "model card")
            if context < min_context:
                problems.append(
                    "%s holds %d tokens of context, and the task "
                    "needs at least %d."
                    % (name, context, min_context))

    max_size = task.get("max_size_gb")
    if max_size is not None:
        max_size = _as_number(max_size, "max_size_gb", "task")
        size = card.get("size_gb")
        if size is None:
            warnings.append(
                "The model card does not say how big %s is, so "
                "the size limit could not be checked." % name)
        else:
            size = _as_number(size, "size_gb", "model card")
            if size > max_size:
                problems.append(
                    "%s is %.1f GB, over the %.1f GB limit for "
                    "this task." % (name, size, max_size))

    if available_bytes is not None:
        size = card.get("size_gb")
        if size is not None:
            size = _as_number(size, "size_gb", "model card")
            verdict = ram_mod.check(
                int(size * 1024 ** 3),
                meminfo={"MemAvailable": available_bytes // 1024,
                         "MemTotal": available_bytes // 1024})
            if not verdict["fits"]:
                problems.append(
                    "%s needs %.1f GB and only %s is free. "
                    "It will not fit in RAM."
                    % (name, size,
                       ram_mod.format_gb(available_bytes)))

    return (not problems, problems, warnings)


def plain_report(name, suitable, problems, warnings):
    """The verdict in plain words."""
    lines = []
    for warning in warnings:
        lines.append("Warning: " + warning)
    if suitable:
        lines.append(
            "%s looks able to do this job. You can load it."
            % (name or "This model"))
    else:
        lines.append(
            "Do not load %s for this job:" % (name or "this model"))
        for problem in problems:
            lines.append("  - " + problem)
        lines.append("Pick a model that can do the job instead.")
    return "\n".join(lines) + "\n"
