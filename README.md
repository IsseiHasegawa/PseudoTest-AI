# PseudoTest AI — Phases 1 and 2

A Python CLI that detects **pseudo-tested function candidates** using two
function-body replacements and **hybrid static/dynamic selection** of relevant
pytest test cases. Phase 1 runs entirely locally: **no Nemotron/API calls** and
**no generated tests**. The separately invoked Phase 2 sends only selected
source/test context to Nemotron and validates generated tests on the original
and both mutants.

## Installation

Python **3.10+** and pytest are required. Install the tool in the same Python
environment used by the target project; the current environment is reused for
all test runs. For example, from outside the target repository:

```bash
python -m pip install /path/to/PseudoTest-AI
```

With [uv](https://docs.astral.sh/uv/), create the project environment and run
the CLI with:

```bash
cd /path/to/PseudoTest-AI
uv sync
uv run pseudotest --help
```

For development, run the test suite with `uv run pytest tests/ -q`.

You can also use `python -m pip install -e /path/to/PseudoTest-AI` while
contributing to the tool. Dependencies for the *target project* must already be
installed in that environment. Do **not** install PseudoTest AI by copying its
package files into the repository to be analyzed.

## Example: analyze another repository

```bash
cd /path/to/my-python-repo
pseudotest analyze \
  --target src/calculator.py \
  --test-cmd "python -m pytest tests/ -q" \
  --timeout 60 \
  --output ../my-pseudotest-output
```

The current directory is the project root. `--target` is a path *inside* that
root. `--test-cmd` must be a pytest invocation with at least one test file or
directory, not an arbitrary shell command; supported arguments include `-q`,
`-v`, `-s`, `--tb=short`, `--color=no` and other display flags. No `-n`, `-k`,
`-m`, `--cov`, shell pipes, or arbitrary pytest plugin options in this initial
version. The tool runs pytest with the CLI's own instrumentation plugin and
explicit node IDs on mutant runs; test suite `addopts` are disabled so they do
not secretly change the selection or start parallel workers. The actual
Python interpreter is the one running the `pseudotest` CLI.

The output directory defaults to a sibling directory of the repo:
`../<repo-name>-pseudotest-output`. The CLI refuses an output directory that is
inside the project or that contains the project. The layout is:

```text
my-pseudotest-output/
  results/
    analysis.json
```

The JSON includes the original target SHA256, test-file SHA256 values (under
`tests/`), function locations, dynamic and static pytest node IDs, selected
node IDs, observed return type, mutant results and per-mutant timing. It is
suitable as input for a separately invoked improvement phase.

### Try the included example

```bash
cd /path/to/PseudoTest-AI/examples/sample_repo
pseudotest analyze --target src/calculator.py --test-cmd "python -m pytest tests/ -q"
```

Expected categories include `discount` as a pseudo-tested candidate, `add`
and `total` as detected by their tests, and `unused` as not covered.

## Phase 2: Improve with Nemotron (separate command)

Phase 2 **does not rerun Phase 1**. It reads `results/analysis.json`, checks
that the target source and recorded test files still match their SHA256 values,
and attempts to generate tests only for `PSEUDO_TESTED_CANDIDATE` functions.
If your repository changed since analysis, run `analyze` again first.

An NVIDIA Build API key is required to use the real Nemotron service. Set it
**locally**, not in command flags, files, or chat messages:

```bash
export NVIDIA_API_KEY='YOUR_OWN_NVIDIA_API_KEY'
# Or set NVIDIA_NIM_API_KEY instead.
```

From any directory, using the **same Python environment** as the target repo:

```bash
pseudotest improve \
  --report /path/to/pseudotest-output/results/analysis.json \
  --output /path/to/pseudotest-output \
  --max-attempts 3
```

The CLI defaults to NVIDIA's `nvidia/nemotron-3-super-120b-a12b` model with
`https://integrate.api.nvidia.com/v1/chat/completions`. Choose a currently
available model if your account does not have access:

```bash
pseudotest improve --report /path/to/analysis.json \
  --model nvidia/nemotron-3-super-120b-a12b \
  --api-timeout 90 --timeout 60
```

For each candidate, Nemotron receives the target function's original source,
selected test functions and imports (up to input limits), and the two constant
mutants. Only related excerpts are sent, **not the full repository by default**.
Nonetheless those excerpts may contain confidential source or data: use this
feature only on code authorized for transmission to the configured provider.
The tool never sends the API key inside the prompt.

The generated test module is executed in fresh full-project copies for
`original`, `mutant1`, and `mutant2`. A generated test must call the target,
PASS on original, and KILL both mutants (with the failed tests themselves
executing the target). Only then is it written to the **external**
`generated-tests/` folder. Unsuccessful/partial generations are not saved as
approved tests. Invalid code or partial kills can trigger a retry; timeouts
end that candidate's attempts. The external output layout is:

```text
pseudotest-output/
  results/analysis.json
  generated-tests/test_pseudotest_<function>_<ordinal>.py
  reports/improvement.json
```

The `improvement.json` report records test statuses, attempt counts and the
2-mutant score for successfully improved candidates (0% -> 100%). When a
candidate is not improved its after-score is **unknown**, not assumed to be
0%. Generated tests remain outside the original repo; review and copy them
into the project's test suite yourself if they are suitable. When you later
re-run `analyze`, do so with a test suite containing the accepted new tests.

**Security:** A temporary project copy is file isolation, not a security
sandbox. AI-generated Python tests are untrusted executable code and can
access the network, files and accounts available to your Python process.
Review generated code and run the tool in a restricted/trusted environment
before applying it to sensitive repositories. Phase 2 does not guarantee
complete test correctness or overall project mutation-score improvement; it
checks precisely the two configured function-body mutants.

**Python environment:** On macOS/Homebrew do not use
`--break-system-packages`. Activate the same existing virtual environment you
used to install PseudoTest AI. If `python` is aliased in zsh, use the explicit
`/path/to/.venv/bin/python` interpreter to install the package.

## Detection policy

1. Copy the entire project into an external temporary workspace, then run the
   supplied pytest suite once for a passing baseline. Run no mutations when
   baseline tests fail. The original repo is not edited.
2. For each test's setup, call, and teardown, record calls to target-file
   functions and their observed Python return types. Extract an AST call graph
   for direct/transitive imports and resolvable calls. Select the **union** of
   tests identified by either technique, at the pytest node-ID level. Tests
   identified by neither are outside the analysis of that function.
3. Analyze only regular **top-level, undecorated, synchronous** functions,
   excluding generators. Return types are inferred from normal baseline
   execution (not from annotations). Only functions observed to return a
   *single* type from `bool`, `int`, `float`, `str` are eligible. Multiple,
   missing, and unsupported observed return types are out of scope.
4. Make two independent mutants, replacing the whole body with:

   | Type | Mutant 1 | Mutant 2 |
   | --- | --- | --- |
   | `bool` | `False` | `True` |
   | `int` | `0` | `1` |
   | `float` | `0.0` | `1.0` |
   | `str` | `""` | `"mutant"` |

5. Each mutant is tested in its own freshly copied project. If both mutants
   are actually executed and *all selected tests pass*, label the function
   `PSEUDO_TESTED_CANDIDATE`. If either mutant is killed by a test failure,
   classify it as `DETECTED` or `PARTIALLY_DETECTED` as appropriate. Baseline
   skips on selected tests, mutant skips, collection/import/setup/teardown
   errors, timeouts, or a mutant that was not executed are **inconclusive**,
   never pseudo-tested. The default timeout is **60 seconds per pytest run**;
   change it using `--timeout <seconds>`.
6. Print candidate names and line numbers. Save the JSON result in the
   external output folder. Delete all mutation workspaces even on failure.

`PSEUDO_TESTED_CANDIDATE` is **relative to the selected tests and the two
particular mutants**. It does not prove that the function is untested in every
possible sense; detecting both mutants does not prove the function is fully
covered either. Unknown static Python constructs are not assumed to be safe.

## Environment and safety limits

- The project copy is **file isolation, not a security sandbox**. The target
  suite runs executable Python with the current user's rights and may reach
  network services, absolute paths, external databases, or installed editable
  packages. Run only **trusted** project tests. We check whether the original
  target module was called instead of its working copy when profiling, but
  cannot guarantee unrelated side effects outside the project.
- Run from the repository root. The output directory must be external.
  Local `.git`, `.venv`, `venv`, caches, `node_modules`, and symbolic links are
  omitted from the copy; tests depending on them may not be supported.
- We use a **single pytest process** (no xdist); `sys.setprofile()` traces the
  executing test's thread. Background threads/processes, collection-time
  function calls, custom runners, test ordering dependencies, monkeypatching
  and fully dynamic dispatch are not completely handled. A missing or
  ambiguous relationship may be excluded from selected tests.
- AST regeneration is applied **only to temporary mutants**. It can alter
  source formatting and is not guaranteed to preserve esoteric syntax or
  module-level side effects. Such cases should be treated as experimental.
- The runner kills the pytest process group on POSIX on timeout and always
  removes its own temporary copies. Test-created external processes not in
  that group or external side effects are outside this guarantee.
- A mutant that fails from an assertion or runtime exception *during the test
  call*, after the mutated function ran, counts as killed. Collection,
  import, setup, teardown, skip and timeout are not counted as kills.
- The `results/analysis.json` file is overwritten on each analysis using the
  same output path. Keep separate output folders to retain earlier runs.

## Develop and test

```bash
cd /path/to/PseudoTest-AI
uv sync
uv run pytest tests/ -q
```

The test suite includes unit checks and subprocess-based integration tests for
hybrid selection, untouched source files, unsupported return types, skips,
strict classification, and **offline fake-Nemotron Phase 2 validation**.
Actual NVIDIA API connectivity requires your own key and is not verified by
the offline test suite. An actual target project's behavior may differ; review
its README and test requirements before running.
