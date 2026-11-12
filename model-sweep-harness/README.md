# T5 — model-sweep-harness

Pairs with skill **S13** (model sweep + roster audit, hardware-graded).

Scripted benchmark/compat table builder: feed it a JSON list of model candidates, get a graded Markdown table + ranked trial list with exact pull tags.

## What it does

- Grades each candidate (A/B/C/D) from RAM fit, licence openness, runtime compat, and benchmark evidence.
- Flags models exceeding the RAM ceiling (default 8 GB, `--ram-gb` to change) as **OVER CEILING** and rejects them — they cannot load on the machine.
- Flags every vendor benchmark as **UNREPRODUCED** — vendor-card numbers, never measured on the target machine, never presented as fact.
- Emits a ranked trial list with exact `ollama pull <tag>` commands, plus a rejects list (do-not-re-propose without new evidence).

## Candidate file format (JSON)

```json
{
  "machine": {"ram_gb": 8, "cpu_only": true},
  "candidates": [
    {"name": "qwen3-vl", "tag": "qwen3-vl:2b-instruct",
     "params_b": 2, "quant": "Q4_K_M", "size_gb": 1.9,
     "licence": "Apache-2.0",
     "runtimes": ["ollama"],
     "seats": ["vision"],
     "vendor_benchmarks": [
       {"name": "MMMU", "score": 62.1, "source": "vendor model card"}],
     "notes": "Vision seat."}
  ]
}
```

See `candidates.sample.json` for a complete sample (5 candidates, including one deliberately over-ceiling and one with no runtime).

## Requirements

Python 3.8+, stdlib only. No network — everything comes from the input file.

## Usage

```bash
python3 sweep.py candidates.sample.json
python3 sweep.py candidates.json --ram-gb 8 --out sweep-report.md
```

## Smoke test

```bash
bash smoke_test.sh
```

Runs on the sample file and checks the output table contains the over-ceiling flag and the expected trial/reject counts.
