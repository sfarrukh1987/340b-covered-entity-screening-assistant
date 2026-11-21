"""Run with python -m screening after installing the pinned requirements."""

import argparse
import csv
from pathlib import Path
import sys

from .inputs import load_bundle
from .model_steps import LocalOllamaBackend, SyntheticBackend
from .workflow import run_workflow, write_reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the synthetic 340B screening rough draft.")
    parser.add_argument("--input-dir", type=Path, default=Path("fixtures/synthetic"))
    parser.add_argument("--out-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--ollama-model", help="Opt in to a preinstalled local model for synthetic inputs.")
    args = parser.parse_args(argv)
    try:
        bundle = load_bundle(args.input_dir)
        backend = LocalOllamaBackend(args.ollama_model) if args.ollama_model else SyntheticBackend()
        rows, metadata = run_workflow(bundle, backend)
        write_reports(args.out_dir, rows, metadata)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"Workflow stopped: {exc}", file=sys.stderr)
        return 1
    counts = " | ".join(
        f"{label}={sum(row['screen']['action'] == label for row in rows)}"
        for label in ("review", "verify", "hold")
    )
    print(f"Synthetic run: {len(rows)} candidates | {counts}")
    print(f"Reports: {args.out_dir / 'audit.html'} and {args.out_dir / 'shortlist.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
