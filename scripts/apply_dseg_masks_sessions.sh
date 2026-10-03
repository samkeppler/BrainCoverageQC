#!/bin/bash
# =============================================================================
# Transform MNI-space brain coverage masks into subject ACPC space.
#
# For every subject/session in a QSIPrep derivatives folder, applies the
# QSIPrep-generated MNI152NLin2009cAsym -> ACPC composite transform to four
# region masks (ICBM152 whole brain, superior cerebrum, inferior cerebrum,
# cerebellum/midbrain), using the session's ACPC-space dwiref as reference.
#
# Outputs:
#   - Per subject/session: four ACPC-space masks in
#     OUTPUT_DIR/sub-<id>/ses-<id>/masks/sub-<id>_space-ACPC_<mask>.nii.gz
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
die () { echo "ERROR: $*" 1>&2; exit 1; }

# Return all sessions for a subject (e.g., "ses-1 ses-2"), or "" if none.
list_sessions () {
  local qsiprep_root="$1"
  local subj="$2"
  local hit
  hit=$(ls -d "${qsiprep_root}/sub-${subj}"/ses-* 2>/dev/null || true)
  if [[ -z "$hit" ]]; then
    echo ""
    return 0
  fi
  for d in $hit; do basename "$d"; done
}

# Return ses-1 if present, else the first session found.
default_session () {
  local qsiprep_root="$1"
  local subj="$2"
  local s
  s=$(list_sessions "$qsiprep_root" "$subj")
  if [[ -z "$s" ]]; then
    echo ""
    return 0
  fi
  for x in $s; do
    if [[ "$x" == "ses-1" ]]; then
      echo "ses-1"
      return 0
    fi
  done
  echo "$s" | awk '{print $1}'
}

# Return the ACPC-space dwiref for a subject/session, or "" if not found.
find_dwiref () {
  local qsiprep_root="$1"
  local subj="$2"
  local ses="$3"   # "ses-1" / "ses-2" / ""

  local dwi_dir
  if [[ -n "$ses" ]]; then
    dwi_dir="${qsiprep_root}/sub-${subj}/${ses}/dwi"
  else
    dwi_dir="${qsiprep_root}/sub-${subj}/dwi"
  fi

  local prefix
  if [[ -n "$ses" ]]; then
    prefix="sub-${subj}_${ses}_"
  else
    prefix="sub-${subj}_"
  fi

  local hit
  hit=$(ls -1 "${dwi_dir}/${prefix}"dir-*_space-ACPC_dwiref.nii.gz 2>/dev/null | head -n 1 || true)
  if [[ -n "$hit" ]]; then echo "$hit"; return 0; fi

  hit=$(ls -1 "${dwi_dir}/${prefix}"space-ACPC_dwiref.nii.gz 2>/dev/null | head -n 1 || true)
  if [[ -n "$hit" ]]; then echo "$hit"; return 0; fi

  hit=$(ls -1 "${dwi_dir}/${prefix}"*_space-ACPC_dwiref.nii.gz 2>/dev/null | head -n 1 || true)
  echo "$hit"
}

# Return the MNI -> ACPC transform. QSIPrep writes it at the subject level
# (shared across sessions), not per session.
find_subject_level_xfm () {
  local qsiprep_root="$1"
  local subj="$2"
  local xfm="${qsiprep_root}/sub-${subj}/anat/sub-${subj}_from-MNI152NLin2009cAsym_to-ACPC_mode-image_xfm.h5"
  if [[ -f "$xfm" ]]; then
    echo "$xfm"
    return 0
  fi
  echo ""
}


# -----------------------------------------------------------------------------
# TRANSFORMS
# -----------------------------------------------------------------------------
# Apply the MNI -> ACPC transform to one mask with antsApplyTransforms in Docker.
apply_xfm_mni2acpc_mask_docker () {
  local xfm_dir="$1"
  local xfm_name="$2"
  local in_file="$3"
  local out_file="$4"
  local ref_file="$5"
  local interp="$6"

  [[ -f "$in_file" ]]  || { echo "Skipping - missing input: $in_file"; return 0; }
  [[ -f "$ref_file" ]] || { echo "Skipping - missing ref:   $ref_file"; return 0; }

  local xfm_path="${xfm_dir}/${xfm_name}"
  [[ -f "$xfm_path" ]] || { echo "Skipping - missing xfm:   $xfm_path"; return 0; }

  local in_dir out_dir ref_dir
  in_dir="$(dirname "$in_file")"
  out_dir="$(dirname "$out_file")"
  ref_dir="$(dirname "$ref_file")"
  mkdir -p "$out_dir"

  local in_base out_base ref_base
  in_base="$(basename "$in_file")"
  out_base="$(basename "$out_file")"
  ref_base="$(basename "$ref_file")"

  docker run --rm \
    -v "$in_dir":/input:ro \
    -v "$out_dir":/output \
    -v "$xfm_dir":/xfm:ro \
    -v "$ref_dir":/ref:ro \
    "${ANTS_DOCKER_IMAGE}" \
    antsApplyTransforms \
      -i "/input/$in_base" \
      -t "/xfm/$xfm_name" \
      -r "/ref/$ref_base" \
      -o "/output/$out_base" \
      -n "$interp"
}


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
main () {
  command -v docker >/dev/null 2>&1 || die "docker not found in PATH"

  local qsiprep_root="${QSIPREP_ROOT}"
  [[ -d "$qsiprep_root" ]] || die "QSIPREP_ROOT not found: $qsiprep_root"
  [[ -d "${MNI_MASKS_DIR}" ]] || die "MNI_MASKS_DIR not found: ${MNI_MASKS_DIR}"
  [[ -f "${ICBM152_MASK_FILE}" ]] || die "ICBM152 mask not found: ${ICBM152_MASK_FILE}"

  local braincov_root="${OUTPUT_DIR}"
  mkdir -p "$braincov_root"

  local subj_dir subj
  for subj_dir in "${qsiprep_root}"/sub-*; do
    [[ -d "$subj_dir" ]] || continue
    subj="$(basename "$subj_dir")"
    subj="${subj#sub-}"

    # Process every session found on disk for this subject
    local all_sessions
    all_sessions="$(list_sessions "$qsiprep_root" "$subj")"
    if [[ -z "$all_sessions" ]]; then
      echo "Skipping sub-${subj}: no session folders found"
      continue
    fi

    # De-duplicate sessions
    local uniq=()
    for s in $all_sessions; do
      local seen="false"
      for u in "${uniq[@]}"; do [[ "$u" == "$s" ]] && seen="true"; done
      [[ "$seen" == "false" ]] && uniq+=("$s")
    done

    local xfm_path
    xfm_path="$(find_subject_level_xfm "$qsiprep_root" "$subj")"
    if [[ -z "$xfm_path" ]]; then
      echo "Skipping sub-${subj}: missing subject-level xfm: ${qsiprep_root}/sub-${subj}/anat/sub-${subj}_from-MNI152NLin2009cAsym_to-ACPC_mode-image_xfm.h5"
      continue
    fi
    local xfm_dir xfm_name
    xfm_dir="$(dirname "$xfm_path")"
    xfm_name="$(basename "$xfm_path")"

    for ses in "${uniq[@]}"; do
      local ref_file out_mask_dir

      ref_file="$(find_dwiref "$qsiprep_root" "$subj" "$ses")"
      if [[ -z "$ref_file" ]]; then
        echo "Skipping - could not find dwiref for sub-${subj} ${ses}"
        continue
      fi

      out_mask_dir="${braincov_root}/sub-${subj}/${ses}/masks"
      mkdir -p "$out_mask_dir"

      echo "============================================="
      echo "Subject: sub-${subj} ${ses}"
      echo "Output dir:   $out_mask_dir"
      echo "Reference:    $ref_file"
      echo "Transform:    $xfm_path"

      for mask_key in "${MASKS[@]}"; do
        local in_file stem tag out_file

        if [[ "$mask_key" == "__ICBM152__" ]]; then
          in_file="${ICBM152_MASK_FILE}"
          stem="__ICBM152__"
        else
          in_file="${MNI_MASKS_DIR}/${mask_key}"
          stem="${mask_key%.nii.gz}"
        fi

        tag="${OUTTAG[$stem]}"
        out_file="${out_mask_dir}/sub-${subj}_space-ACPC_${tag}.nii.gz"

        # Overwrite on rerun
        rm -f "$out_file"

        apply_xfm_mni2acpc_mask_docker \
          "$xfm_dir" \
          "$xfm_name" \
          "$in_file" \
          "$out_file" \
          "$ref_file" \
          "${INTERP}"

        echo "  Wrote: $out_file"
      done
    done

  done
}

main "$@"