"""Generate precomputed population metadata CSVs.

For every population in epydemix-data, writes:

- ``app/data/population_metadata.csv`` — the default 5-group aggregation
  (e.g. ``0-4, 5-19, 20-49, 50-64, 65+``). Long format:
  ``name,age_group,population``.
- ``app/data/population_age_distribution.csv`` — the raw single-year
  distribution straight from the upstream ``age_distribution.csv``. Long
  format: ``name,age,population``.

Both files seed the runtime metadata cache at startup so ``GET /v1/populations``
and ``GET /v1/populations/{name}`` can return rich responses without live-loading
every country on boot.

Re-run this script whenever the upstream epydemix-data release changes, and
commit both regenerated CSVs alongside the dependency bump.

Usage:
    uv run python scripts/build_population_metadata.py
"""

from __future__ import annotations

import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from epydemix.population.population import (
    get_available_locations,
    load_epydemix_population,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
AGGREGATED_OUTPUT = REPO_ROOT / "app" / "data" / "population_metadata.csv"
RAW_OUTPUT = REPO_ROOT / "app" / "data" / "population_age_distribution.csv"
RAW_BASE_URL = "https://raw.githubusercontent.com/epistorm/epydemix-data/main/data"
MAX_WORKERS = 8


def compute_aggregated(name: str) -> tuple[str, list[tuple[str, int]]] | tuple[str, None]:
    """Load a population via epydemix and return (name, [(age_group, count), ...])."""
    try:
        pop = load_epydemix_population(population_name=name)
        pairs = [(str(label), int(count)) for label, count in zip(pop.Nk_names, pop.Nk)]
        return name, pairs
    except Exception as exc:
        print(f"  aggregated failed: {name}: {exc}", file=sys.stderr)
        return name, None


def fetch_raw_distribution(name: str) -> tuple[str, list[tuple[str, int]]] | tuple[str, None]:
    """Fetch the raw per-single-year distribution CSV for a population."""
    url = f"{RAW_BASE_URL}/{name}/demographic/age_distribution.csv"
    try:
        df = pd.read_csv(url)
        pairs = [(str(row["group_name"]), int(row["value"])) for _, row in df.iterrows()]
        return name, pairs
    except Exception as exc:
        print(f"  raw failed: {name}: {exc}", file=sys.stderr)
        return name, None


def write_long_csv(path: Path, header: list[str], entries: dict[str, list[tuple[str, int]]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for name in sorted(entries):
            for label, count in entries[name]:
                writer.writerow([name, label, count])
                rows_written += 1
    return rows_written


def run_parallel(
    worker,
    locations: list[str],
    label: str,
) -> dict[str, list[tuple[str, int]]]:
    print(f"{label}: loading {len(locations)} populations with {MAX_WORKERS} workers...")
    t0 = time.time()
    entries: dict[str, list[tuple[str, int]]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(worker, name): name for name in locations}
        for i, future in enumerate(as_completed(futures), 1):
            name, pairs = future.result()
            if pairs is None:
                continue
            entries[name] = pairs
            if i % 50 == 0:
                print(f"  {label}: {i}/{len(locations)}")
    elapsed = time.time() - t0
    print(f"{label}: {len(entries)}/{len(locations)} in {elapsed:.1f}s")
    return entries


def main() -> int:
    locations = get_available_locations()["location"].tolist()

    aggregated = run_parallel(compute_aggregated, locations, "aggregated")
    raw = run_parallel(fetch_raw_distribution, locations, "raw")

    agg_rows = write_long_csv(AGGREGATED_OUTPUT, ["name", "age_group", "population"], aggregated)
    raw_rows = write_long_csv(RAW_OUTPUT, ["name", "age", "population"], raw)

    print()
    print(f"Wrote {agg_rows} rows ({len(aggregated)} populations) -> {AGGREGATED_OUTPUT}")
    print(f"Wrote {raw_rows} rows ({len(raw)} populations) -> {RAW_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
