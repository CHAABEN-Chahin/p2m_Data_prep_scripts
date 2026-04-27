#!/usr/bin/env python3
"""
Build a 3D nodule patch dataset from LIDC-IDRI NIfTI + pylidc annotations.

For each nodule cluster found via pylidc, this script:
  1. Loads the matching reconstructed NIfTI volume.
  2. Resamples it to 1 mm isotropic spacing.
  3. Computes the consensus mask centroid in the original voxel space.
  4. Maps the centroid through physical coordinates into the resampled space.
  5. Extracts a 48x48x48 patch centred on the centroid.
  6. Normalises HU to [0, 1] and saves as float32 .npy.
  7. Records all metadata (malignancy label, centroid, voxel counts) in manifest.csv.

Usage
-----
  python build_patch_dataset.py outputs_native_full patches_dataset
  python build_patch_dataset.py outputs_native_full patches_dataset --patch-size 48 --overwrite

Output layout
-------------
  patches_dataset/
    patches/
      LIDC_IDRI_0001_<uid_prefix>_nod00.npy
      ...
    manifest.csv
"""

import argparse
import csv
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import SimpleITK as sitk
from tqdm import tqdm

# pylidc references deprecated numpy aliases on some versions.
if not hasattr(np, "int"):
    np.int = int

import pylidc as pl

try:
    from pylidc.utils import consensus as pylidc_consensus
except Exception:
    pylidc_consensus = None

from extract_patch import (
    resample_volume_isotropic,
    centroid_to_resampled_index,
    extract_patch_3d,
    normalize_patch,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_series_uid(xml_path: str) -> Optional[str]:
    """Extract SeriesInstanceUid from LIDC CT XML (namespace-safe)."""
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return None
    for elem in root.iter():
        if elem.tag.split("}")[-1] == "SeriesInstanceUid":
            return elem.text.strip() if elem.text else None
    return None


def _discover_series_folders(root_dir: str) -> list[str]:
    """Return sorted list of folders containing at least one .nii.gz and one .xml."""
    found = []
    for folder in Path(root_dir).rglob("*"):
        if not folder.is_dir():
            continue
        children = list(folder.iterdir())
        has_nifti = any(c.name.endswith(".nii.gz") for c in children if c.is_file())
        has_xml   = any(c.name.lower().endswith(".xml") for c in children if c.is_file())
        if has_nifti and has_xml:
            found.append(str(folder))
    return sorted(found)


def _consensus_centroid_ijk(
    cmask: np.ndarray,
    cbbox: Tuple,
) -> Tuple[float, float, float]:
    """
    Compute centroid of a pylidc consensus mask in nibabel/sitk index (i,j,k) space.

    cbbox is a 3-tuple of slice objects that place cmask into the full volume array.
    Falls back to the bbox centre when the consensus mask is empty.
    """
    indices = np.argwhere(cmask > 0)  # (N, 3) in local cmask space
    if len(indices) == 0:
        return tuple((s.start + s.stop) / 2.0 for s in cbbox)

    offsets = np.array([cbbox[0].start, cbbox[1].start, cbbox[2].start], dtype=float)
    global_centroid = (indices.astype(float) + offsets).mean(axis=0)
    return (float(global_centroid[0]), float(global_centroid[1]), float(global_centroid[2]))


def _aggregate_malignancy(nod_group) -> Tuple[float, int, list]:
    """
    Aggregate per-reader malignancy scores (1-5) for a nodule cluster.

    Returns (mean_float, rounded_label_1_to_5, list_of_raw_ratings).
    """
    ratings = [int(ann.malignancy) for ann in nod_group if ann.malignancy is not None]
    if not ratings:
        return 0.0, 0, []
    mean_val = float(np.mean(ratings))
    label = int(round(mean_val))
    label = max(1, min(5, label))
    return mean_val, label, ratings


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")


# ── main builder ─────────────────────────────────────────────────────────────

def build_patch_dataset(
    input_root: str,
    output_dir: str,
    patch_size: int = 48,
    target_spacing: float = 1.0,
    consensus_level: float = 0.5,
    overwrite: bool = False,
) -> dict:
    """
    Build patch dataset and write manifest.csv.

    Parameters
    ----------
    input_root      : folder tree containing per-series folders (NIfTI + XML)
    output_dir      : where to write patches/ and manifest.csv
    patch_size      : cubic patch edge length in voxels (after resampling)
    target_spacing  : isotropic voxel size in mm to resample to before patch extraction
    consensus_level : pylidc clevel for consensus mask (0.5 = majority agreement)
    overwrite       : if False, skip existing .npy files (still add them to manifest)
    """
    if pylidc_consensus is None:
        raise RuntimeError(
            "pylidc.utils.consensus is unavailable. "
            "Verify your pylidc installation."
        )

    patches_dir   = os.path.join(output_dir, "patches")
    manifest_path = os.path.join(output_dir, "manifest.csv")
    os.makedirs(patches_dir, exist_ok=True)

    series_folders = _discover_series_folders(input_root)
    print(f"Series folders found: {len(series_folders)}")

    stats = {
        "series_found":    len(series_folders),
        "series_matched":  0,
        "series_no_scan":  0,
        "nodules_saved":   0,
        "nodules_skipped_existing": 0,
        "errors":          0,
    }
    rows = []

    fieldnames = [
        "patch_file",
        "patient_id",
        "series_uid",
        "nodule_idx",
        "centroid_i",
        "centroid_j",
        "centroid_k",
        "centroid_resampled_x",
        "centroid_resampled_y",
        "centroid_resampled_z",
        "malignancy_mean",
        "malignancy_label",
        "n_readers",
        "reader_ratings",
        "nodule_voxels",
    ]

    for folder in tqdm(series_folders, desc="Building patches"):
        files     = os.listdir(folder)
        nifti_f   = next((f for f in files if f.endswith(".nii.gz")), None)
        xml_f     = next((f for f in files if f.lower().endswith(".xml")), None)
        if not nifti_f or not xml_f:
            continue

        nifti_path = os.path.join(folder, nifti_f)
        xml_path   = os.path.join(folder, xml_f)

        series_uid = _get_series_uid(xml_path)
        if not series_uid:
            continue

        scan = pl.query(pl.Scan).filter(pl.Scan.series_instance_uid == series_uid).first()
        if not scan:
            stats["series_no_scan"] += 1
            continue

        stats["series_matched"] += 1

        try:
            orig_sitk      = sitk.ReadImage(nifti_path)
            resampled_sitk = resample_volume_isotropic(orig_sitk, target_spacing=target_spacing)
            # sitk.GetArrayFromImage returns (z, y, x) numpy array
            vol_zyx = sitk.GetArrayFromImage(resampled_sitk).astype(np.float32)

            nodules = scan.cluster_annotations()
            for nod_idx, nod_group in enumerate(nodules):
                try:
                    cmask, cbbox, _ = pylidc_consensus(nod_group, clevel=consensus_level)

                    # Centroid in original nibabel/sitk (i,j,k) index space
                    centroid_ijk = _consensus_centroid_ijk(cmask, cbbox)

                    # Map to resampled sitk index (rx, ry, rz)
                    rx, ry, rz = centroid_to_resampled_index(
                        centroid_ijk, orig_sitk, resampled_sitk
                    )

                    # Extract patch: numpy is (z,y,x) so centroid is (rz, ry, rx)
                    patch = extract_patch_3d(
                        vol_zyx,
                        centroid_zyx=(rz, ry, rx),
                        patch_size=patch_size,
                    )
                    patch = normalize_patch(patch)

                    mal_mean, mal_label, mal_ratings = _aggregate_malignancy(nod_group)

                    patch_name = (
                        f"{_safe(scan.patient_id or 'unknown')}"
                        f"_{_safe(series_uid)[:28]}"
                        f"_nod{nod_idx:02d}.npy"
                    )
                    patch_path = os.path.join(patches_dir, patch_name)
                    rel_path   = os.path.join("patches", patch_name)

                    if os.path.exists(patch_path) and not overwrite:
                        stats["nodules_skipped_existing"] += 1
                    else:
                        np.save(patch_path, patch)
                        stats["nodules_saved"] += 1

                    rows.append({
                        "patch_file":            rel_path,
                        "patient_id":            scan.patient_id or "",
                        "series_uid":            series_uid,
                        "nodule_idx":            nod_idx,
                        "centroid_i":            round(centroid_ijk[0], 2),
                        "centroid_j":            round(centroid_ijk[1], 2),
                        "centroid_k":            round(centroid_ijk[2], 2),
                        "centroid_resampled_x":  rx,
                        "centroid_resampled_y":  ry,
                        "centroid_resampled_z":  rz,
                        "malignancy_mean":       round(mal_mean, 3),
                        "malignancy_label":      mal_label,
                        "n_readers":             len(mal_ratings),
                        "reader_ratings":        ",".join(str(r) for r in mal_ratings),
                        "nodule_voxels":         int(cmask.sum()),
                    })

                except Exception as exc:
                    stats["errors"] += 1
                    print(f"  [nodule {nod_idx}] {folder}: {exc}")

        except Exception as exc:
            stats["errors"] += 1
            print(f"[series error] {folder}: {exc}")

    # Write manifest
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    stats["total_in_manifest"] = len(rows)
    stats["manifest_csv"]      = manifest_path
    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build 3D nodule patch dataset from LIDC-IDRI series folders."
    )
    parser.add_argument(
        "input_root",
        help="Root folder containing per-series folders (each with a .nii.gz and a .xml)",
    )
    parser.add_argument(
        "output_dir",
        help="Output directory — patches/ subfolder and manifest.csv will be written here",
    )
    parser.add_argument(
        "--patch-size",
        type=int,
        default=48,
        help="Cubic patch edge in voxels after resampling (default: 48)",
    )
    parser.add_argument(
        "--target-spacing",
        type=float,
        default=1.0,
        help="Isotropic voxel spacing in mm before patch extraction (default: 1.0)",
    )
    parser.add_argument(
        "--consensus-level",
        type=float,
        default=0.5,
        help="pylidc consensus clevel — fraction of readers required to agree (default: 0.5)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .npy patch files",
    )
    args = parser.parse_args()

    stats = build_patch_dataset(
        input_root=args.input_root,
        output_dir=args.output_dir,
        patch_size=args.patch_size,
        target_spacing=args.target_spacing,
        consensus_level=args.consensus_level,
        overwrite=args.overwrite,
    )

    print("\nDataset build complete")
    for key, val in stats.items():
        print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
