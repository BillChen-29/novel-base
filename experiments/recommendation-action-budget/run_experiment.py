#!/usr/bin/env python3
"""Compare candidate budgets using a prepared local run and imported reviews."""
from pathlib import Path
from runpy import run_path


_vector_runner = run_path(str(Path(__file__).resolve().parents[1] / 'recommendation-vector/run_experiment.py'))
run = _vector_runner['run']


def main(argv=None):
    return _vector_runner['main'](argv, prepared_runs_only=True)


if __name__ == '__main__':
    raise SystemExit(main())
