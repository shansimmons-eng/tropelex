# Drift-Bench

A small, deterministic benchmark measuring how well Tropelex's real
detectors (Ghost Decisions, Contradiction Detection, Injection Sentinel,
the assertion-weakening detector, the handoff-completeness check) catch
six drift/injection threat categories — run against production code
directly, not mocks. See [`docs/cais-summary.md`](../../docs/cais-summary.md)
for the currently-published results and their honest interpretation.

## Run it

```bash
python3 scripts/driftbench_run.py            # runs and persists
python3 scripts/driftbench_run.py --no-persist  # dry run, no disk write
```

Reproduces the exact table published in `docs/cais-summary.md`, externally,
from a plain checkout of this repo — no dashboard server, no project setup.

## How a scenario works

Every scenario is a `Scenario` dataclass (defined in
[`core/driftbench/__init__.py`](__init__.py)):

```python
@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    description: str
    expect_detection: bool          # ground truth: is this a real violation?
    run: Callable[[], bool]         # what actually happened when checked
```

`run` is a zero-arg closure that calls a **real Tropelex detector directly**
against fixture data (a synthetic decision + diff, or a synthetic memory
dict) and returns whether it flagged something. `expect_detection` and
`run()`'s result are allowed to disagree — that disagreement is the point
of a benchmark. A scenario whose `run()` correctly comes back `False`
against an `expect_detection=True` fixture isn't a bug; it's an honestly
measured gap (see `core/driftbench/scenarios.py`'s own module docstring
for two real, currently-published examples of exactly this).

## Adding a scenario

1. Pick (or add) a category constant in `core/driftbench/__init__.py`'s
   `CATEGORIES` tuple.
2. Write a `run: Callable[[], bool]` closure in
   `core/driftbench/scenarios.py` that calls the real detector you're
   testing — never a mock, never a hand-computed "expected" value standing
   in for the detector's actual output.
3. Add both a positive (`expect_detection=True`, a genuine violation) and
   a negative (`expect_detection=False`, clean/benign) scenario for any
   new category — `tests/test_driftbench.py`'s
   `test_corpus_has_at_least_one_positive_and_negative_per_category` enforces
   this.
4. Verify the scenario against the real detector *before* trusting it:
   run `scenario.run()` by hand and confirm the result is what you expect,
   the same discipline every existing scenario's docstring already follows.
5. Add a `test_scenario_matches_ground_truth`-style parametrized case in
   `tests/test_driftbench.py` if the scenario is expected to pass (i.e. its
   `run()` result should match `expect_detection`) — a scenario documenting
   a known gap gets its own explicit test instead (see
   `test_reward_hacking_positive_is_a_documented_known_gap` for the pattern).

## Corpus versioning

`core/driftbench/__init__.py`'s `CORPUS_VERSION` is included in every
persisted report (`memory/driftbench/latest.json`) and every
`/api/driftbench/latest` response, so a published metric can name exactly
which corpus it refers to instead of an implicit "whatever the corpus
happened to contain that day."

**Bump `CORPUS_VERSION` when:**
- A scenario is added or removed.
- An existing scenario's `expect_detection` changes (its ground-truth
  label was wrong, or the fixture itself changed).

**Don't bump it for:**
- Wording-only changes to a `description`.
- A scenario's *measured* `run()` result changing because a detector got
  better (that's real, checkable progress on the existing corpus — the
  ground truth the corpus tests against didn't move, only the code being
  tested did).
