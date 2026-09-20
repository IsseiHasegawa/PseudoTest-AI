# PseudoTest AI demonstration — Campus Shop (30 functions)

This is an **independent, intentionally mixed-quality test project**, not the
PseudoTest AI tool itself. The single target file is `src/checkout.py` and it
contains **exactly 30** ordinary synchronous top-level functions. The
`tests/test_checkout.py` suite has **30 passing tests** by design.

Functions model small store operations (prices, coupons, customer IDs,
shipping, loyalty, and receipts). They return only `bool`, `int`, `float`, or
`str` in the baseline. None deliberately raises exceptions; that avoids the
known `NoneType` profiling issue in the current PseudoTest AI release.

## Expected result using the current two-mutant catalogue

| Group | Number of functions | Expected Phase 1 classification |
| --- | ---: | --- |
| Type-only assertions (weak) | 6 | `PSEUDO_TESTED_CANDIDATE` |
| One-sided assertions (partial) | 9 | `PARTIALLY_DETECTED` |
| Behavior assertions (detected) | 15 | `DETECTED` |

The first six are intentionally weak for **demonstration purposes**. They
should not be presented as defects found in an unrelated production project.
The `test_subtotal_cents_weak` case calls through `_receipt_subtotal()` to show
that a test can be relevant to a function without calling it directly.

## Run on a Mac where PseudoTest AI is already installed

Unzip this archive **outside** the PseudoTest AI tool source folder, then:

```bash
cd ~/Downloads/PseudoTest-Demo-30
source ~/Downloads/PseudoTest-AI-Unified/PseudoTest-AI/.venv/bin/activate
python3 -m pytest tests/ -q
pseudotest analyze \
  --target src/checkout.py \
  --test-cmd "python3 -m pytest tests/ -q" \
  --timeout 60 \
  --output ../pseudotest-demo-30-output
```

**Virtual environment location can vary.** If the `source` command above does
not match your installation, activate the environment where `pseudotest` is
installed, or call its `bin/pseudotest` executable by absolute path. The same
Python environment must have pytest installed.

Phase 1 prints the six pseudo-tested candidates and saves
`../pseudotest-demo-30-output/results/analysis.json`.

### Optional Phase 2 — requires an NVIDIA API key

```bash
pseudotest improve \
  --report ../pseudotest-demo-30-output/results/analysis.json \
  --max-attempts 2
```

Phase 2 is a **separate invocation** and may call Nemotron for each of the six
pseudo-tested candidates, consuming API credits. Set `NVIDIA_API_KEY` in your
local shell first. Nemotron output is not deterministic; improvement is not
guaranteed. Successful generated tests are saved outside this demo repo under
`../pseudotest-demo-30-output/generated-tests/`.

To independently rerun Phase 1 with generated tests, **copy the entire demo
project** to a second folder outside the original repo and copy the reviewed,
verified tests into that copy's `tests/` directory. Run `analyze` from the copy
with a new `--output` path. The original demo repo remains unchanged.

## Files

```text
PseudoTest-Demo-30/
├── src/
│   ├── __init__.py
│   └── checkout.py         # all 30 target functions live here
├── tests/
│   └── test_checkout.py    # 30 tests, intentionally mixed strength
├── pyproject.toml
├── .gitignore
└── README.md
```

The demo's 0%, 50%, and 100% per-function scores mean only detection of the
**two configured return-value mutants**; they do not measure comprehensive
test adequacy.
