# 1_rationalization

Decide which WebFOCUS business logic carries into LookML.

The Proof of Technology implementation lives in [`pot/`](pot/README.md). Run it with:

```bash
uv run python 1_rationalization/pot/main.py --run-id RUN_ID
```

`uv run python 1_rationalization/main.py --run-id RUN_ID` calls the same entrypoint.

The `phase_*` folders keep the full-build ladder (retire, exclude, consolidate, rebuild, migrate). For the POT those steps are explicit no-ops or the structural catalog, and the code for all of them is under `pot/`.
