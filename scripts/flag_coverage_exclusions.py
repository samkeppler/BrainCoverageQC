#!/usr/bin/env python3
"""
Flag participants for inclusion/exclusion based on brain coverage thresholds.

Each applied coverage metric is categorized as full, minimally cropped, or
cropped using two thresholds per metric. A participant is excluded if they
fail any applied metric, and flagged as undetermined if they fail none but
are missing at least one. Summary counts are per participant; a participant
with several rows (e.g., sessions) is included if at least one row passes.

Outputs:
    - CSV of coverage categories, pass/fail per metric, and overall
      excluded/undetermined flags (one row per input row)
"""

import os
from datetime import datetime

import pandas as pd


# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
INPUT_DATA_PATH = "/path/to/your/input/data/input_data.csv"
OUTPUT_DIR = "/path/to/your/output/folder"

OUTPUT_CSV_NAME = "coverage_exclusion_flags.csv"

# Input CSV column names
ID_COL = "participant_id"
DATASET_COL = "dataset"  # set to None if the input CSV has no dataset column

# Metric -> coverage column
COVERAGE_COLS = {
    "full_brain_mask": "coverage_full_brain_mask",
    "regional_masks": "min_coverage_regional_masks",
}

# Two coverage thresholds (%) per metric: coverage >= "full" -> full;
# between "cropped" and "full" -> minimally cropped; below "cropped" ->
# cropped. "full" must be greater than "cropped".
THRESHOLDS = {
    "full_brain_mask": {"full": 98, "cropped": 90},
    "regional_masks": {"full": 95, "cropped": 85},
}

# How to treat the "minimally cropped" band:
#   "pass" -- grouped with full (participant passes that metric)
#   "fail" -- grouped with cropped (participant fails that metric)
MINIMALLY_CROPPED_TREATMENT = "pass"

# Metrics to apply; a participant is excluded if they fail any of these
METRICS_TO_APPLY = ["full_brain_mask", "regional_masks"]


# ----------------------------------------------------------------------
# INPUT
# ----------------------------------------------------------------------
def validate_config():
    """Check that the CONFIG settings are complete and consistent."""
    if not METRICS_TO_APPLY:
        raise ValueError("METRICS_TO_APPLY is empty -- specify at least one metric")

    if MINIMALLY_CROPPED_TREATMENT not in ("pass", "fail"):
        raise ValueError(
            "MINIMALLY_CROPPED_TREATMENT must be 'pass' or 'fail', "
            f"got: {MINIMALLY_CROPPED_TREATMENT!r}"
        )

    for metric in METRICS_TO_APPLY:
        if metric not in COVERAGE_COLS:
            raise ValueError(f"Metric '{metric}' in METRICS_TO_APPLY has no entry in COVERAGE_COLS")
        if metric not in THRESHOLDS:
            raise ValueError(f"Metric '{metric}' in METRICS_TO_APPLY has no entry in THRESHOLDS")

        thr = THRESHOLDS[metric]
        if "full" not in thr or "cropped" not in thr:
            raise ValueError(f"THRESHOLDS['{metric}'] must have both 'full' and 'cropped' keys")
        if thr["full"] <= thr["cropped"]:
            raise ValueError(
                f"THRESHOLDS['{metric}']: 'full' ({thr['full']}) must be greater than "
                f"'cropped' ({thr['cropped']})"
            )


def load_input():
    """Read the input CSV and check that all required columns are present."""
    if not os.path.exists(INPUT_DATA_PATH):
        raise FileNotFoundError(f"Input CSV not found: {INPUT_DATA_PATH}")

    df = pd.read_csv(INPUT_DATA_PATH)
    df.columns = [c.strip() for c in df.columns]

    required = [ID_COL] + [COVERAGE_COLS[m] for m in METRICS_TO_APPLY]
    if DATASET_COL:
        required.append(DATASET_COL)

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Input CSV is missing required column(s): {missing}")

    return df


# ----------------------------------------------------------------------
# FLAGGING
# ----------------------------------------------------------------------
def categorize_coverage(coverage, full_threshold, cropped_threshold):
    """Map a numeric coverage Series to 'full' / 'minimally_cropped' /
    'cropped' / 'undetermined' (missing)."""
    category = pd.Series("cropped", index=coverage.index, dtype=object)
    category[coverage >= cropped_threshold] = "minimally_cropped"
    category[coverage >= full_threshold] = "full"
    category[coverage.isna()] = "undetermined"
    return category


def flag_participants(df):
    """Categorize each applied metric and build the flags table (one row per input row)."""
    out = pd.DataFrame()
    out[ID_COL] = df[ID_COL]
    if DATASET_COL:
        out[DATASET_COL] = df[DATASET_COL]

    fail_flags = pd.DataFrame(index=df.index)
    undetermined_flags = pd.DataFrame(index=df.index)
    minimal_flags = pd.DataFrame(index=df.index)

    for metric in METRICS_TO_APPLY:
        col = COVERAGE_COLS[metric]
        thr = THRESHOLDS[metric]
        coverage = pd.to_numeric(df[col], errors="coerce")
        category = categorize_coverage(coverage, thr["full"], thr["cropped"])

        out[col] = coverage
        out[f"{metric}_category"] = category

        fails_this_metric = (category == "cropped") | (
            (category == "minimally_cropped") & (MINIMALLY_CROPPED_TREATMENT == "fail")
        )
        # Nullable boolean so undetermined participants get <NA> rather
        # than True/False for that metric
        out[f"{metric}_pass"] = (~fails_this_metric).astype("boolean")
        out.loc[category == "undetermined", f"{metric}_pass"] = pd.NA

        fail_flags[metric] = fails_this_metric
        undetermined_flags[metric] = category == "undetermined"
        minimal_flags[metric] = category == "minimally_cropped"

    # A failure on any metric excludes the participant even if another
    # metric is missing; undetermined applies only when nothing failed
    out["excluded"] = fail_flags.any(axis=1)
    out["undetermined"] = undetermined_flags.any(axis=1) & ~out["excluded"]
    out["any_minimally_cropped"] = minimal_flags.any(axis=1)

    def joined(flags_df, row_idx):
        return ", ".join(m for m in METRICS_TO_APPLY if flags_df.loc[row_idx, m])

    out["failed_metrics"] = [joined(fail_flags, i) for i in df.index]
    out["undetermined_metrics"] = [joined(undetermined_flags, i) for i in df.index]
    out["minimally_cropped_metrics"] = [joined(minimal_flags, i) for i in df.index]

    return out


def summarize_participants(results):
    """Collapse rows to one status per participant (keyed by dataset and ID):
    included if at least one row passes, else undetermined if any row is
    undetermined, else excluded (every row failed)."""
    key = [DATASET_COL, ID_COL] if DATASET_COL else [ID_COL]
    flags = results[key + ["excluded", "undetermined", "any_minimally_cropped"]].copy()
    flags["passed"] = ~flags["excluded"] & ~flags["undetermined"]

    per_participant = flags.groupby(key).agg(
        included=("passed", "any"),
        undetermined=("undetermined", "any"),
        any_minimally_cropped=("any_minimally_cropped", "any"),
    )
    per_participant["undetermined"] &= ~per_participant["included"]
    per_participant["excluded"] = ~per_participant["included"] & ~per_participant["undetermined"]
    return per_participant


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    validate_config()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_csv = os.path.join(OUTPUT_DIR, OUTPUT_CSV_NAME)

    start = datetime.now()
    print(f"Started at {start}")
    print(f"Input CSV:                     {INPUT_DATA_PATH}")
    print(f"Output CSV:                    {output_csv}")
    print(f"Metrics applied:               {METRICS_TO_APPLY}")
    print(f"Thresholds:                    { {m: THRESHOLDS[m] for m in METRICS_TO_APPLY} }")
    print(f"Minimally cropped treatment:   {MINIMALLY_CROPPED_TREATMENT}")

    df = load_input()
    results = flag_participants(df)
    results.to_csv(output_csv, index=False)

    per_participant = summarize_participants(results)
    n_participants = len(per_participant)
    print(f"Loaded {len(df)} rows ({n_participants} participants)")

    n_included = int(per_participant["included"].sum())
    n_excluded = int(per_participant["excluded"].sum())
    n_undetermined = int(per_participant["undetermined"].sum())
    n_minimal = int(per_participant["any_minimally_cropped"].sum())

    print(f"\nSaved flags for {len(results)} rows to: {output_csv}")
    print(f"Participants:             {n_participants}")
    print(f"  Included:               {n_included}")
    print(f"  Excluded:               {n_excluded}")
    print(f"  Undetermined:           {n_undetermined}")
    print(f"  (of which, landed in 'minimally cropped' band on >=1 metric: {n_minimal})")
    print(f"Total runtime: {datetime.now() - start}")


if __name__ == "__main__":
    main()