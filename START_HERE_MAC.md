# PseudoTest AI: unified installation on macOS

This folder contains **both** commands in one Python project:

- `pseudotest analyze` — local test relevance and mutation analysis (no Nemotron API).
- `pseudotest improve` — read an existing report and generate / validate tests with Nemotron.

The old Phase 1 and Phase 2 directories are not needed for this installation. **Do not delete them until the new installation has been verified.**

## Install without changing Homebrew's Python

Unzip to `~/Downloads/PseudoTest-AI`, then run:

```bash
cd ~/Downloads/PseudoTest-AI
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
./.venv/bin/pseudotest --help
```

You should see **both** `analyze` and `improve`. Using the executable by its full path avoids a shell alias or deactivated environment issue. If your shell already has a `pseudotest` from the older venv, use `~/Downloads/PseudoTest-AI/.venv/bin/pseudotest` instead.

### Using uv

If you have [uv](https://docs.astral.sh/uv/) installed, the equivalent setup is:

```bash
cd ~/Downloads/PseudoTest-AI
uv sync
uv run pseudotest --help
```

Run the test suite with `uv run pytest tests/ -q`. The `uv.lock` file pins the
resolved dependencies for reproducible setup.

## Run against an external repository

The repository under test stays outside this tool folder. Install its test dependencies into the **new** `.venv` above using its own project instructions, then:

```bash
cd ~/Downloads/opensource-test/mutation-demo
~/Downloads/PseudoTest-AI/.venv/bin/pseudotest analyze \
  --target src/calc.py \
  --test-cmd 'python3 -m pytest tests/ -q' \
  --output ../pseudotest-output-mutation-demo-unified
```

If that report contains pseudo-tested candidates, configure `NVIDIA_API_KEY` locally and run:

```bash
~/Downloads/PseudoTest-AI/.venv/bin/pseudotest improve \
  --report ../pseudotest-output-mutation-demo-unified/results/analysis.json
```

Neither command requires copying the tool into the repository under test. Reports and generated tests go in the sibling output folder, not the target repository.

## Existing output reports

You can keep previous output folders. If you invoke `improve` with a previous `analysis.json`, its existing source/test integrity checks still apply. You do **not** need to copy old reports into the tool directory.

## One important distinction

Both phases now live in one **project**, but are intentionally separate **commands**: invoking `analyze` does not make API calls or generate tests, and `improve` does not rerun the analysis.
