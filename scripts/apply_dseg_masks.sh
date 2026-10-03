#!/bin/bash
# =============================================================================
# Transform MNI-space brain coverage masks into subject ACPC space
# (datasets without session folders).
#
# For every subject in a QSIPrep derivatives folder, applies the
# QSIPrep-generated MNI152NLin2009cAsym -> ACPC composite transform to four
# region masks (ICBM152 whole brain, superior cerebrum, inferior cerebrum,
# cerebellum/midbrain), using the subject's ACPC-space dwiref as reference.
#
# Outputs:
#   - Per subject: four ACPC-space masks in
#     OUTPUT_DIR/sub-<id>/masks/sub-<id>_space-ACPC_<mask>.nii.gz
#
# Requirements:
#   - bash 4+ (associative arrays)
#   - Docker (runs antsApplyTransforms from the ANTs image)
# =============================================================================

set -euo pipefail


# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
QSIPREP_ROOT="/path/to/your/qsiprep/derivatives"
MNI_MASKS_DIR="/path/to/your/mni/masks/folder"
ICBM152_MASK_FILE="/path/to/your/icbm152/mni_icbm152_t1_tal_nlin_asym_09c_mask.nii"
OUTPUT_DIR="${QSIPREP_ROOT}/brain_coverage"

# {subj} is replaced with the subject ID
XFM_NAME_TEMPLATE="sub-{subj}_from-MNI152NLin2009cAsym_to-ACPC_mode-image_xfm.h5"

ANTS_DOCKER_IMAGE="antsx/ants:2.5.3"

# Nearest-neighbor keeps transformed masks binary
INTERP="NearestNeighbor"

# Input masks; "__ICBM152__" refers to ICBM152_MASK_FILE
MASKS=(
  "__ICBM152__"
  "MNI152NLin2009cAsym_superior_cerebrum.nii.gz"
  "MNI152NLin2009cAsym_inferior_cerebrum.nii.gz"
  "MNI152NLin2009cAsym_cerebellum+midbrain.nii.gz"
)

# Input mask stem -> output file tag
declare -A OUTTAG=(
  ["__ICBM152__"]="mni_icbm152_brain_coverage_mask"
  ["MNI152NLin2009cAsym_superior_cerebrum"]="mni_superior_cerebrum_brain_coverage_mask"
  ["MNI152NLin2009cAsym_inferior_cerebrum"]="mni_inferior_cerebrum_brain_coverage_mask"
  ["MNI152NLin2009cAsym_cerebellum+midbrain"]="mni_cerebellum_and_midbrain_brain_coverage_mask"
)

# -----------------------------------------------------------------------------
# FILE DISCOVERY
# -----------------------------------------------------------------------------
die () {
  echo "ERROR: $*" 1>&2
  exit 1
}

# Print subject IDs (without the "sub-" prefix), one per line, sorted.
get_subject_list () {
  local qsiprep_dir_path="$1"
  local subj_dir base

  for subj_dir in "${qsiprep_dir_path}"/sub-*/; do
    [[ -d "$subj_dir" ]] || continue
    base="$(basename "$subj_dir")"
    echo "${base#sub-}"
  done | sort
}

# Return the ACPC-space dwiref for a subject, or "" if not found.
find_dwiref () {
  local qsiprep_dir_path="$1"
  local subj="$2"
  local dwi_dir="${qsiprep_dir_path}/sub-${subj}/dwi"

  local hit
  hit=$(ls -1 "${dwi_dir}/sub-${subj}"_dir-*_space-ACPC_dwiref.nii.gz 2>/dev/null | head -n 1 || true)
  [[ -n "$hit" ]] && { echo "$hit"; return; }

  hit="${dwi_dir}/sub-${subj}_space-ACPC_dwiref.nii.gz"
  [[ -f "$hit" ]] && { echo "$hit"; return; }

  hit=$(ls -1 "${dwi_dir}/sub-${subj}"*_space-ACPC_dwiref.nii.gz 2>/dev/null | head -n 1 || true)
  [[ -n "$hit" ]] && { echo "$hit"; return; }

  echo ""
}


# -----------------------------------------------------------------------------
# TRANSFORMS
# -----------------------------------------------------------------------------
# Apply the MNI -> ACPC transform to one mask with antsApplyTransforms in Docker.
apply_xfm_mni2acpc_mask_docker () {
  local qsiprep_dir_path="$1"
  local subj="$2"
  local in_file="$3"
  local out_file="$4"
  local ref_file="$5"
  local interp="$6"

  [[ -f "$in_file" ]] || { echo "Skipping - missing input: $in_file"; return 0; }
  [[ -f "$ref_file" ]] || { echo "Skipping - missing reference: $ref_file"; return 0; }

  local xfm_dir="${qsiprep_dir_path}/sub-${subj}/anat"
  local xfm_name="${XFM_NAME_TEMPLATE//\{subj\}/$subj}"
  local xfm_path="${xfm_dir}/${xfm_name}"

  [[ -f "$xfm_path" ]] || { echo "Skipping - missing transform: $xfm_path"; return 0; }

  echo "---------------------------------------------"
  echo "subject: sub-${subj}"
  echo "input:   $in_file"
  echo "output:  $out_file"

  local in_dir out_dir ref_dir
  in_dir="$(dirname "$in_file")"
  out_dir="$(dirname "$out_file")"
  ref_dir="$(dirname "$ref_file")"
  mkdir -p "$out_dir"

  docker run --rm \
    -v "$in_dir":/input:ro \
    -v "$out_dir":/output \
    -v "$xfm_dir":/xfm:ro \
    -v "$ref_dir":/ref:ro \
    "${ANTS_DOCKER_IMAGE}" \
    antsApplyTransforms \
      -i "/input/$(basename "$in_file")" \
      -t "/xfm/$xfm_name" \
      -r "/ref/$(basename "$ref_file")" \
      -o "/output/$(basename "$out_file")" \
      -n "$interp"

  echo "Wrote: $out_file"
}


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
main () {
  command -v docker