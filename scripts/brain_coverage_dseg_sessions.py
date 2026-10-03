#!/usr/bin/env python3
"""
Brain coverage of DWI data within ACPC-space masks (datasets with sessions).

For each subject and session found in a QSIPrep derivatives folder,
binarizes the time-averaged preprocessed DWI and computes the percentage
of each ACPC-space brain coverage mask (ICBM152 whole brain, superior
cerebrum, inferior cerebrum, cerebellum/midbrain) that it covers.

Outputs:
    - One CSV per session of per-subject coverage (%) for each mask
"""

import os
import shutil
from glob import glob
from datetime import datetime
from typing import Optional
from collections import OrderedDict

import pandas as pd
import nibabel as nib
from nipype.interfaces import fsl
from nipype.interfaces.fsl.maths import MathsCommand


# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
QSIPREP_ROOT = "/path/to/your/qsiprep/derivatives"
MASKS_ROOT = os.path.join(QSIPREP_ROOT, "brain_coverage")
OUTPUT_DIR = os.path.join(MASKS_ROOT, "results")

OUTPUT_CSV_TEMPLATE = "brain_coverage_dseg_masks_{ses}.csv"

# Sessions to process; subjects are discovered per session from
# QSIPREP_ROOT/sub-*/<ses>/
SESSIONS = ["ses-1", "ses-2"]

# DWI filename part after "<subj>_<ses>_", e.g. for
# sub-XXXX_ses-1_dir-PA_space-ACPC_desc-preproc_dwi.nii.gz.
# Can be overridden with the DWI_PREFIX environment variable.
DWI_PREFIX = "dir-PA_space-ACPC"

# Mask name -> path template. Also sets the output column order.
# Mask filenames do not include the session.
MASK_TEMPLATES = OrderedDict([
    ("icbm152", "{masks_root}/{subj}/{ses}/masks/{subj}_space-ACPC_mni_icbm152_brain_coverage_mask.nii.gz"),
    ("superior_cerebrum", "{masks_root}/{subj}/{ses}/masks/{subj}_space-ACPC_mni_superior_cerebrum_brain_coverage_mask.nii.gz"),
    ("inferior_cerebrum", "{masks_root}/{subj}/{ses}/masks/{subj}_space-ACPC_mni_inferior_cerebrum_brain_coverage_mask.nii.gz"),
    ("cerebellum_and_midbrain", "{masks_root}/{subj}/{ses}/masks/{subj}_space-ACPC_mni_cerebellum_and_midbrain_brain_coverage_mask.nii.gz"),
])

# Use the first matching DWI file if the expected filename is not found
ALLOW_WILDCARD_FALLBACK = True
KEEP_INTERMEDIATES = False
VERBOSE = True


# ----------------------------------------------------------------------
# FILE DISCOVERY
# ----------------------------------------------------------------------
def get_subject_list(qsiprep_root: str, ses: str):
    """Return sorted subject folder names that contain the given session."""
    subs = sorted(
        os.path.basename(p)
        for p in glob(os.path.join(qsiprep_root, "sub-*"))
        if os.path.isdir(p) and os.path.isdir(os.path.join(p, ses))
    )
    if not subs:
        raise RuntimeError(f"No subject folders with {ses} found under: {qsiprep_root}")
    return subs


def find_preproc_dwi(subj: str, ses: str, qsiprep_root: str, dwi_prefix: str, allow_fallback: bool) -> Optional[str]:
    """Return the preprocessed DWI for a subject/session, expected at
    <subj>/<ses>/dwi/<subj>_<ses>_<dwi_prefix>_desc-preproc_dwi.nii.gz.
    If missing and allow_fallback is set, returns the first file matching
    <subj>_<ses>_*_desc-preproc_dwi.nii.gz; otherwise None."""
    expected = os.path.join(
        qsiprep_root, subj, ses, "dwi",
        f"{subj}_{ses}_{dwi_prefix}_desc-preproc_dwi.nii.gz",
    )
    if os.path.exists(expected):
        return expected

    if not allow_fallback:
        return None

    pattern = os.path.join(qsiprep_root, subj, ses, "dwi", f"{subj}_{ses}_*_desc-preproc_dwi.nii.gz")
    candidates = sorted(glob(pattern))
    if candidates:
        print(f"  [WARN] Expected DWI not found for {subj} {ses} (expected: {os.path.basename(expected)}).")
        print(f"         Falling back to first match: {os.path.basename(candidates[0])}")
        return candidates[0]

    return None


# ----------------------------------------------------------------------
# COVERAGE
# ----------------------------------------------------------------------
def count_nonzero_voxels(img_path: str) -> float:
    """Count nonzero voxels in a NIfTI image."""
    data = nib.load(img_path).get_fdata()
    return float((data != 0).sum())


def binarize_mean_dwi(subj: str, ses: str, dwi_file: str, work_dir: str) -> Optional[str]:
    """Convert the DWI to float, average over time, and binarize. Returns
    the binarized image path, or None if the float conversion fails."""
    subj_tmp = os.path.join(work_dir, ses, subj)
    os.makedirs(subj_tmp, exist_ok=True)

    dwi_float = os.path.join(subj_tmp, f"{subj}_{ses}_dwi_float.nii.gz")
    dwi_mean = os.path.join(subj_tmp, f"{subj}_{ses}_dwi_meanT.nii.gz")
    dwi_mean_bin = os.path.join(subj_tmp, f"{subj}_{ses}_dwi_meanT_bin.nii.gz")

    MathsCommand(
        in_file=dwi_file,
        out_file=dwi_float,
        output_datatype="float",
        output_type="NIFTI_GZ"
    ).run()

    if not os.path.exists(dwi_float):
        return None

    fsl.MeanImage(
        in_file=dwi_float,
        out_file=dwi_mean,
        dimension="T",
        output_type="NIFTI_GZ"
    ).run()

    fsl.UnaryMaths(
        in_file=dwi_mean,
        out_file=dwi_mean_bin,
        operation="bin",
        output_type="NIFTI_GZ"
    ).run()

    return dwi_mean_bin


def compute_coverage(subj: str, ses: str, mask_name: str, dwi_mean_bin: str, mask_file: str, work_dir: str) -> Optional[float]:
    """Percent of mask voxels covered by the binarized DWI, rounded to
    3 decimals. Returns None if masking fails or the mask is empty."""
    masked = os.path.join(work_dir, ses, subj, f"{subj}_{ses}_{mask_name}_masked.nii.gz")

    fsl.ApplyMask(
        in_file=dwi_mean_bin,
        mask_file=mask_file,
        out_file=masked,
        output_type="NIFTI_GZ"
    ).run()

    if not os.path.exists(masked):
        return None

    n_mask = count_nonzero_voxels(mask_file)
    if n_mask == 0:
        return None

    n_cov = count_nonzero_voxels(masked)
    return round((n_cov / n_mask) * 100.0, 3)


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    start = datetime.now()
    print(f"Started at {start}")

    dwi_prefix = os.environ.get("DWI_PREFIX", DWI_PREFIX)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    work_dir = os.path.join(OUTPUT_DIR, "tmp")
    os.makedirs(work_dir, exist_ok=True)

    print(f"QSIPrep root: {QSIPREP_ROOT}")
    print(f"Masks root: {MASKS_ROOT}")
    print(f"DWI prefix: {dwi_prefix} (allow fallback: {ALLOW_WILDCARD_FALLBACK})")

    for ses in SESSIONS:
        out_csv = os.path.join(OUTPUT_DIR, OUTPUT_CSV_TEMPLATE.format(ses=ses))

        mask_templates = OrderedDict(
            (k, v.format(masks_root=MASKS_ROOT, subj="{subj}", ses=ses))
            for k, v in MASK_TEMPLATES.items()
        )

        subjects = get_subject_list(QSIPREP_ROOT, ses)
        total = len(subjects)

        print(f"\n--- Processing {ses} ({total} subjects) ---")
        print(f"Output CSV: {out_csv}")

        rows = []
        for i, subj in enumerate(subjects, 1):
            print(f"[{ses} {i}/{total}] Processing {subj} ...", flush=True)

            dwi_file = find_preproc_dwi(
                subj=subj,
                ses=ses,
                qsiprep_root=QSIPREP_ROOT,
                dwi_prefix=dwi_prefix,
                allow_fallback=ALLOW_WILDCARD_FALLBACK,
            )

            row = {"participant_id": subj}

            if dwi_file is None:
                for name in mask_templates:
                    row[f"coverage_{name}"] = None
                rows.append(row)
                continue

            dwi_mean_bin = binarize_mean_dwi(subj, ses, dwi_file, work_dir)

            for name, tmpl in mask_templates.items():
                mask_file = tmpl.format(subj=subj)

                if not os.path.exists(mask_file):
                    if VERBOSE:
                        print(f"  [WARN] Missing mask for {subj} {ses}: {mask_file}")
                    row[f"coverage_{name}"] = None
                    continue

                if dwi_mean_bin is None:
                    row[f"coverage_{name}"] = None
                    continue

                row[f"coverage_{name}"] = compute_coverage(subj, ses, name, dwi_mean_bin, mask_file, work_dir)

            rows.append(row)

            if not KEEP_INTERMEDIATES:
                shutil.rmtree(os.path.join(work_dir, ses, subj), ignore_errors=True)

        df = pd.DataFrame(rows)

        ordered_cols = ["participant_id"] + [f"coverage_{k}" for k in mask_templates.keys()]
        df = df.reindex(columns=ordered_cols)

        df.to_csv(out_csv, index=False)
        print(f"Saved {ses} brain coverage results to: {out_csv}")

    print(f"\nTotal runtime: {datetime.now() - start}")

    if not KEEP_INTERMEDIATES:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()