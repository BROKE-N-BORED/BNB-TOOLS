# T9 — brand-scrub-rename

Pairs with skill **S30** (brand scrub + rename-with-migration). From the Forge no-brands scrub (235 substitutions, 28 files) and the Goldfish→GoFish rename (351 substitutions, 14 files, migrations so user state carried over).

## What it does

1. Walks the tree (skipping `.git`, `__pycache__`, `.venv`, `.forge`, `node_modules`, and binary files — detected by NUL byte, not extension).
2. Reports every file + match count **before changing anything**. **Dry-run is the default**; `--apply` writes.
3. After `--apply`, runs a case-insensitive whole-tree grep for the old string to catch stragglers (the step that caught a missed file in the Forge scrub).
4. With `--key-renames` (JSON mapping old state key → new state key), generates migration scaffolding: a JSON mapping file + a `migrate.py` snippet that renames keys in a state dict, so existing user data (plans, toggles, skill on/off) survives the rename.

Substitution is literal by default (`--regex` enables regex), case-sensitive by default (`--ignore-case` for any case).

## Requirements

Python 3.8+, stdlib only. No network.

## Usage

```bash
# Dry run (default): see what would change
python3 scrub.py Goldfish GoFish --tree ./my-project

# Apply, then straggler grep runs automatically
python3 scrub.py Goldfish GoFish --tree ./my-project --apply

# Remove a brand name entirely
python3 scrub.py OldBrand --remove --tree ./my-project --apply

# With state-key migration scaffolding
python3 scrub.py Goldfish GoFish --tree ./my-project --apply \
    --key-renames key-renames.json \
    --mapping-out key-mapping.json --migration-out migrate.py
```

`key-renames.json` format:

```json
{"goldfish_plan": "gofish_plan", "goldfish_enabled": "gofish_enabled"}
```

## Smoke test

```bash
bash smoke_test.sh
```

Dry-run + apply on a sample tree, verifying counts and a clean straggler grep.
