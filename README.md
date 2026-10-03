# Brain Coverage QC for Diffusion MRI

## About

Brain-Coverage-dseg is an automated tool for quantifying brain coverage in MRI data. It calculates coverage metrics for the whole brain, cerebrum, and cerebellum using anatomically defined regional masks, and can flag participants for exclusion based on user-defined coverage thresholds. The tool was developed and validated for diffusion MRI data preprocessed using QSIPrep.

> Portions of the coverage-calculation scripts are adapted from DCAN-Labs' `brain_coverage` project — see [ATTRIBUTION.md](ATTRIBUTION.md) for the source and full list of modifications.

## Installation

**Requirements:**

- Python 3 with `pandas`, `nibabel`, and `nipype`
- FSL (accessed via `nipype.interfaces.fsl`)
- Docker (used to run `antsApplyTransforms` via the `antsx/ants:2.5.3` image)

**Steps:**

1. Clone this repository.
2. Install the required Python packages (`pandas`, `nibabel`, `nipype`).
3. Install FSL and confirm it's available on your system path.
4. Install Docker and pull the `antsx/ants:2.5.3` image.

## Input Data Requirements

Input diffusion MRI data must be processed with QSIPrep before running Brain-Coverage-dseg.

The exclusion-flagging step instead takes a compiled CSV of coverage values as input — see How to Run below.

Input data must be organized according to the
[BIDS standard](https://bids-specification.readthedocs.io/en/stable/) and
preprocessed with QSIPrep. Scripts expect the following structure, where
`sub-XXX` is a participant and `ses-YYY` is a session:

```
QSIPREP_ROOT/
└── sub-XXX/
    ├── anat/
    │   └── sub-XXX_from-MNI152NLin2009cAsym_to-ACPC_mode-image_xfm.h5
    └── ses-YYY/                      # omit for datasets without sessions
        └── dwi/
            ├── sub-XXX_ses-YYY_dir-PA_space-ACPC_desc-preproc_dwi.nii.gz
            └── sub-XXX_ses-YYY_dir-PA_space-ACPC_dwiref.nii.gz
```

For datasets without sessions, files sit directly under `sub-XXX/dwi/` and
file names omit the `ses-YYY` part (e.g.,
`sub-XXX_dir-PA_space-ACPC_desc-preproc_dwi.nii.gz`).

The MNI-space masks are provided separately (`MNI_MASKS_DIR` and
`ICBM152_MASK_FILE` in each script's CONFIG):

```
MNI_MASKS_DIR/
├── MNI152NLin2009cAsym_superior_cerebrum.nii.gz
├── MNI152NLin2009cAsym_inferior_cerebrum.nii.gz
└── MNI152NLin2009cAsym_cerebellum+midbrain.nii.gz

mni_icbm152_t1_tal_nlin_asym_09c_mask.nii
```

## How to Run

Brain-Coverage-dseg runs in three steps. Use the `_sessions` version of each script if your dataset has multiple sessions per subject; otherwise use the single-session version.

1. **Transform the region masks into each subject's diffusion space:**
   ```
   ./apply_dseg_masks.sh
   ```
   or, for multi-session datasets:
   ```
   ./apply_dseg_masks_sessions.sh
   ```
   This aligns the whole-brain, cerebrum, and cerebellum masks to each subject's native diffusion space, using their QSIPrep outputs.

2. **Calculate brain coverage:**
   ```
   python brain_coverage_dseg.py
   ```
   or, for multi-session datasets:
   ```
   python brain_coverage_dseg_sessions.py
   ```
   This calculates, for each subject (and session), what percentage of each region is covered by usable diffusion data.

   Note: the expected DWI filename prefix can be changed via the `DWI_PREFIX` environment variable, if needed.

3. **Flag participants for exclusion:**
   ```
   python flag_coverage_exclusions.py
   ```
   This applies your chosen coverage thresholds to a compiled CSV (one row per subject, with columns `participant_id`, `dataset`, `coverage_full_brain_mask`, and `min_coverage_regional_masks`) and flags each subject as included, excluded, or undetermined.

   Note: `coverage_full_brain_mask` is the `coverage_icbm152` column from step 2's output, and `min_coverage_regional_masks` is the minimum of that output's `coverage_superior_cerebrum`, `coverage_inferior_cerebrum`, and `coverage_cerebellum_and_midbrain` columns. Thresholds, which metrics to apply, and the treatment of borderline ("minimally cropped") cases are set in the script's `CONFIG` block.

## Outputs

- **Single-session datasets:** one CSV file, `brain_coverage/results/brain_coverage_dseg_masks.csv`, with columns `participant_id`, `coverage_icbm152`, `coverage_superior_cerebrum`, `coverage_inferior_cerebrum`, and `coverage_cerebellum_and_midbrain`.
- **Multi-session datasets:** one CSV file per session (e.g., `brain_coverage_dseg_masks_ses-1.csv`, `..._ses-2.csv`), with the same columns.
- **Exclusion flags:** one CSV, `coverage_exclusion_flags.csv`, with one row per subject, including per-metric coverage/category/pass columns plus `excluded`, `undetermined`, and related flag columns.

## Citation

If you use this tool, please cite:

[Paper citation — TBD]

See also the [validation analysis repository](https://github.com/samkeppler/Brain-Coverage-dseg-validation) for the code used to validate this metric against expert manual QC ratings.
