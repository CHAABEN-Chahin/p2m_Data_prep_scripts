#!/usr/bin/env python3
"""Prepare LIDC series folders (NIfTI + XML) into nnU-Net v2 dataset format."""

import argparse
import csv
import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple
import xml.etree.ElementTree as ET

import nibabel as nib
import numpy as np

# pylidc (and related dependencies) may still reference deprecated numpy aliases.
if not hasattr(np, "int"):
    np.int = int

import pylidc as pl
import SimpleITK as sitk
from tqdm import tqdm

try:
    from pylidc.utils import consensus as pylidc_consensus
except Exception:
    pylidc_consensus = None


def get_series_uid_from_xml(xml_path: str) -> Optional[str]:
    """Extract SeriesInstanceUid from LIDC XML with or without namespaces."""
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return None

    for elem in root.iter():
        if elem.tag.split("}")[-1] == "SeriesInstanceUid":
            return elem.text.strip() if elem.text else None
    return None


def sanitize_id(value: str) -> str:
    """Make identifier safe for nnU-Net file names."""
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")


def ensure_pylidc_config(dicom_root: Optional[str], create_if_missing: bool) -> Tuple[bool, str]:
    """Validate or optionally create ~/.pylidcrc for pylidc DICOM lookup."""
    config_path = Path.home() / ".pylidcrc"

    if config_path.exists():
        return True, f"found {config_path}"

    if not create_if_missing:
        return False, (
            f"Missing {config_path}. Create it with:\n"
            "[DICOM]\n"
            "path = /path/to/original/LIDC-IDRI\n"
            "warn = False"
        )

    if not dicom_root:
        return False, "--dicom-root is required when --create-pylidcrc is used"

    if not Path(dicom_root).exists():
        return False, f"--dicom-root does not exist: {dicom_root}"

    dicom_abs = str(Path(dicom_root).resolve())
    config_path.write_text(f"[DICOM]\npath = {dicom_abs}\nwarn = False\n", encoding="utf-8")
    return True, f"created {config_path}"


def check_pylidc_database_ready(allow_empty_db: bool) -> Tuple[bool, str, int]:
    """Check whether pylidc can access its scan index database."""
    try:
        scan_count = pl.query(pl.Scan).count()
    except Exception as exc:
        return False, f"pylidc database query failed: {exc}", 0

    if scan_count == 0 and not allow_empty_db:
        return (
            False,
            "pylidc database contains 0 scans. Ensure your DICOM path is correct in ~/.pylidcrc "
            "and that pylidc indexing has been done.",
            scan_count,
        )

    return True, "pylidc database check passed", scan_count


def find_series_artifacts(series_folder: str) -> Tuple[Optional[str], Optional[str]]:
    """Find one NIfTI and one XML file inside a series folder."""
    files = os.listdir(series_folder)
    nifti_file = next((f for f in files if f.lower().endswith(".nii.gz")), None)
    xml_file = next((f for f in files if f.lower().endswith(".xml")), None)
    return nifti_file, xml_file


def discover_series_folders(input_root: str, recursive: bool = True) -> list[str]:
    """Discover folders that contain at least one .nii.gz and one .xml file."""
    root = Path(input_root)
    if not root.exists() or not root.is_dir():
        return []

    if not recursive:
        candidates = [p for p in root.iterdir() if p.is_dir()]
    else:
        candidates = [p for p in root.rglob("*") if p.is_dir()]

    series_folders = []
    for folder in candidates:
        has_nifti = any(child.is_file() and child.name.lower().endswith(".nii.gz") for child in folder.iterdir())
        if not has_nifti:
            continue
        has_xml = any(child.is_file() and child.name.lower().endswith(".xml") for child in folder.iterdir())
        if has_xml:
            series_folders.append(str(folder))

    return sorted(series_folders)


def save_dataset_json(target_dir: str, dataset_name: str) -> None:
    labels_dir = os.path.join(target_dir, "labelsTr")
    num_training = len([f for f in os.listdir(labels_dir) if f.endswith(".nii.gz")])

    metadata = {
        "name": dataset_name,
        "channel_names": {"0": "CT"},
        "labels": {"background": 0, "nodule": 1},
        "numTraining": num_training,
        "file_ending": ".nii.gz",
    }

    with open(os.path.join(target_dir, "dataset.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)


def make_unique_case_id(base_case_id: str, images_tr: str, labels_tr: str, used_case_ids: set) -> str:
    """Return a unique case id to avoid overwriting existing files."""
    case_id = base_case_id
    suffix = 1
    while (
        case_id in used_case_ids
        or os.path.exists(os.path.join(images_tr, f"{case_id}_0000.nii.gz"))
        or os.path.exists(os.path.join(labels_tr, f"{case_id}.nii.gz"))
    ):
        case_id = f"{base_case_id}_dup{suffix}"
        suffix += 1
    used_case_ids.add(case_id)
    return case_id


def resample_binary_mask_to_shape(mask_np: np.ndarray, target_shape: Tuple[int, int, int]) -> np.ndarray:
    """Resample binary mask to target shape using nearest-neighbor interpolation only."""
    if tuple(mask_np.shape) == tuple(target_shape):
        return mask_np.astype(np.uint8, copy=False)

    # Convert from numpy z,y,x to SimpleITK x,y,z via transpose.
    mask_sitk = sitk.GetImageFromArray(mask_np.astype(np.uint8))
    source_shape_xyz = tuple(reversed(mask_np.shape))
    target_shape_xyz = tuple(reversed(target_shape))

    source_spacing = [
        float(source_shape_xyz[i]) / float(target_shape_xyz[i]) if target_shape_xyz[i] > 0 else 1.0
        for i in range(3)
    ]

    mask_sitk.SetSpacing(source_spacing)
    mask_sitk.SetOrigin((0.0, 0.0, 0.0))
    mask_sitk.SetDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))

    resampler = sitk.ResampleImageFilter()
    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
    resampler.SetOutputSpacing((1.0, 1.0, 1.0))
    resampler.SetSize(target_shape_xyz)
    resampler.SetOutputOrigin((0.0, 0.0, 0.0))
    resampler.SetOutputDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
    resampler.SetDefaultPixelValue(0)

    out_sitk = resampler.Execute(mask_sitk)
    out_np = sitk.GetArrayFromImage(out_sitk).astype(np.uint8)
    out_np[out_np > 0] = 1
    return out_np


def automate_nnunet_prep(
    input_root: str,
    nnunet_raw_dir: str,
    dataset_id: int = 101,
    dataset_name: str = "LungNodule",
    consensus_level: float = 0.5,
    include_empty_cases: bool = True,
    report_name: str = "prep_report.csv",
    resampled_qc_name: str = "resampled_qc.csv",
    qc_major_change_threshold: float = 0.10,
    allow_empty_pylidc_db: bool = False,
    resample_mismatched_masks: bool = True,
    recursive_search: bool = True,
) -> Dict[str, object]:
    """Create nnU-Net v2 imagesTr/labelsTr from series folders and pylidc consensus masks."""
    if pylidc_consensus is None:
        raise RuntimeError(
            "pylidc consensus function is unavailable (expected pylidc.utils.consensus). "
            "Please verify pylidc installation."
        )

    task_name = f"Dataset{dataset_id:03d}_{dataset_name}"
    target_dir = os.path.join(nnunet_raw_dir, task_name)
    images_tr = os.path.join(target_dir, "imagesTr")
    labels_tr = os.path.join(target_dir, "labelsTr")

    os.makedirs(images_tr, exist_ok=True)
    os.makedirs(labels_tr, exist_ok=True)
    report_path = os.path.join(target_dir, report_name)
    resampled_qc_path = os.path.join(target_dir, resampled_qc_name)
    used_case_ids = set()

    db_ok, db_message, scan_count = check_pylidc_database_ready(allow_empty_pylidc_db)
    if not db_ok:
        raise RuntimeError(db_message)

    series_folders = discover_series_folders(input_root, recursive=recursive_search)

    stats = {
        "pylidc_scans_in_db": scan_count,
        "series_folders_found": len(series_folders),
        "folders_seen": 0,
        "processed": 0,
        "skipped_missing_files": 0,
        "skipped_missing_uid": 0,
        "skipped_no_scan": 0,
        "skipped_shape_mismatch": 0,
        "resampled_shape_mismatch": 0,
        "resampled_qc_fail_major": 0,
        "skipped_empty_mask": 0,
        "errors": 0,
    }
    report_rows = []
    resampled_qc_rows = []
    warned_about_resampling = False

    def add_report(
        folder: str,
        nifti_file: Optional[str],
        xml_file: Optional[str],
        series_uid: Optional[str],
        patient_id: Optional[str],
        case_id: Optional[str],
        status: str,
        reason: str,
        nodule_voxels: Optional[int] = None,
        output_image: Optional[str] = None,
        output_label: Optional[str] = None,
        mask_resampled: bool = False,
    ) -> None:
        report_rows.append(
            {
                "folder": folder,
                "nifti_file": nifti_file or "",
                "xml_file": xml_file or "",
                "series_uid": series_uid or "",
                "patient_id": patient_id or "",
                "case_id": case_id or "",
                "status": status,
                "reason": reason,
                "nodule_voxels": "" if nodule_voxels is None else nodule_voxels,
                "mask_resampled": int(mask_resampled),
                "output_image": output_image or "",
                "output_label": output_label or "",
            }
        )

    for folder in tqdm(series_folders, desc="Preparing nnU-Net cases"):
        stats["folders_seen"] += 1

        nifti_file, xml_file = find_series_artifacts(folder)
        if not nifti_file or not xml_file:
            stats["skipped_missing_files"] += 1
            add_report(
                folder=folder,
                nifti_file=nifti_file,
                xml_file=xml_file,
                series_uid=None,
                patient_id=None,
                case_id=None,
                status="skipped",
                reason="missing nifti or xml",
            )
            continue

        xml_path = os.path.join(folder, xml_file)
        nifti_path = os.path.join(folder, nifti_file)

        series_uid = get_series_uid_from_xml(xml_path)
        if not series_uid:
            stats["skipped_missing_uid"] += 1
            add_report(
                folder=folder,
                nifti_file=nifti_file,
                xml_file=xml_file,
                series_uid=None,
                patient_id=None,
                case_id=None,
                status="skipped",
                reason="missing SeriesInstanceUid in xml",
            )
            continue

        try:
            scan = pl.query(pl.Scan).filter(pl.Scan.series_instance_uid == series_uid).first()
            if not scan:
                stats["skipped_no_scan"] += 1
                add_report(
                    folder=folder,
                    nifti_file=nifti_file,
                    xml_file=xml_file,
                    series_uid=series_uid,
                    patient_id=None,
                    case_id=None,
                    status="skipped",
                    reason="no matching scan in pylidc database",
                )
                continue

            vol_nifti = nib.load(nifti_path)
            vol_shape = vol_nifti.shape
            full_mask = np.zeros(vol_shape, dtype=np.uint8)
            was_resampled = False
            case_resample_events = []

            nodules = scan.cluster_annotations()
            for nod_group in nodules:
                cmask, cbbox, _ = pylidc_consensus(nod_group, clevel=consensus_level)
                target_region = full_mask[cbbox]

                # If image grid differs from pylidc consensus grid, skip safely.
                if target_region.shape != cmask.shape:
                    if not resample_mismatched_masks:
                        stats["skipped_shape_mismatch"] += 1
                        add_report(
                            folder=folder,
                            nifti_file=nifti_file,
                            xml_file=xml_file,
                            series_uid=series_uid,
                            patient_id=scan.patient_id,
                            case_id=None,
                            status="skipped",
                            reason=f"shape mismatch: image region {target_region.shape} vs consensus mask {cmask.shape}",
                        )
                        full_mask = None
                        break

                    if not warned_about_resampling:
                        print(
                            "WARNING: shape mismatches detected. Applying nearest-neighbor mask resampling. "
                            "Review outputs carefully for potential geometric misalignment."
                        )
                        warned_about_resampling = True

                    try:
                        orig_shape = tuple(int(v) for v in cmask.shape)
                        orig_voxels = int(cmask.sum())
                        resized_cmask = resample_binary_mask_to_shape(
                            cmask.astype(np.uint8),
                            target_region.shape,
                        )
                        new_shape = tuple(int(v) for v in resized_cmask.shape)
                        new_voxels = int(resized_cmask.sum())
                        voxel_diff = new_voxels - orig_voxels
                        voxel_change_ratio = 0.0 if orig_voxels == 0 else abs(voxel_diff) / float(orig_voxels)
                        qc_status = "FAIL (Major Mismatch)" if voxel_change_ratio > qc_major_change_threshold else "PASS (Minor)"
                        if qc_status.startswith("FAIL"):
                            stats["resampled_qc_fail_major"] += 1
                        case_resample_events.append(
                            {
                                "folder": folder,
                                "series_uid": series_uid,
                                "patient_id": scan.patient_id or "",
                                "consensus_level": consensus_level,
                                "original_shape": str(orig_shape),
                                "new_shape": str(new_shape),
                                "total_voxels_before": orig_voxels,
                                "total_voxels_after": new_voxels,
                                "voxel_count_diff": voxel_diff,
                                "voxel_change_ratio": round(voxel_change_ratio, 6),
                                "qc_major_threshold": qc_major_change_threshold,
                                "qc_status": qc_status,
                            }
                        )
                    except Exception as exc:
                        stats["errors"] += 1
                        add_report(
                            folder=folder,
                            nifti_file=nifti_file,
                            xml_file=xml_file,
                            series_uid=series_uid,
                            patient_id=scan.patient_id,
                            case_id=None,
                            status="error",
                            reason=f"failed nearest-neighbor mask resampling ({exc})",
                        )
                        full_mask = None
                        break

                    full_mask[cbbox] = np.maximum(target_region, resized_cmask)
                    was_resampled = True
                    stats["resampled_shape_mismatch"] += 1
                    continue

                full_mask[cbbox] = np.maximum(target_region, cmask.astype(np.uint8))

            if full_mask is None:
                continue

            full_mask[full_mask > 0] = 1
            nodule_voxels = int(full_mask.sum())
            if (not include_empty_cases) and nodule_voxels == 0:
                stats["skipped_empty_mask"] += 1
                safe_patient = sanitize_id(scan.patient_id or "unknown_patient")
                safe_uid = sanitize_id(series_uid)
                case_id = f"{safe_patient}_{safe_uid}"
                add_report(
                    folder=folder,
                    nifti_file=nifti_file,
                    xml_file=xml_file,
                    series_uid=series_uid,
                    patient_id=scan.patient_id,
                    case_id=case_id,
                    status="skipped",
                    reason="empty mask",
                    nodule_voxels=nodule_voxels,
                    mask_resampled=was_resampled,
                )
                continue

            safe_patient = sanitize_id(scan.patient_id or "unknown_patient")
            safe_uid = sanitize_id(series_uid)
            base_case_id = f"{safe_patient}_{safe_uid}"
            case_id = make_unique_case_id(base_case_id, images_tr, labels_tr, used_case_ids)

            for event in case_resample_events:
                event["case_id"] = case_id
                resampled_qc_rows.append(event)

            label_out = os.path.join(labels_tr, f"{case_id}.nii.gz")
            image_out = os.path.join(images_tr, f"{case_id}_0000.nii.gz")

            # Use original image affine/header to keep image-label geometry consistent.
            mask_header = vol_nifti.header.copy()
            mask_header.set_data_dtype(np.uint8)
            mask_img = nib.Nifti1Image(full_mask, vol_nifti.affine, mask_header)
            nib.save(mask_img, label_out)
            shutil.copy2(nifti_path, image_out)

            stats["processed"] += 1
            add_report(
                folder=folder,
                nifti_file=nifti_file,
                xml_file=xml_file,
                series_uid=series_uid,
                patient_id=scan.patient_id,
                case_id=case_id,
                status="processed",
                reason="ok",
                nodule_voxels=nodule_voxels,
                mask_resampled=was_resampled,
                output_image=image_out,
                output_label=label_out,
            )

        except Exception as exc:
            stats["errors"] += 1
            print(f"Error processing {folder}: {exc}")
            add_report(
                folder=folder,
                nifti_file=nifti_file,
                xml_file=xml_file,
                series_uid=series_uid,
                patient_id=None,
                case_id=None,
                status="error",
                reason=str(exc),
            )

    save_dataset_json(target_dir, dataset_name)
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "folder",
                "nifti_file",
                "xml_file",
                "series_uid",
                "patient_id",
                "case_id",
                "status",
                "reason",
                "nodule_voxels",
                "mask_resampled",
                "output_image",
                "output_label",
            ],
        )
        writer.writeheader()
        writer.writerows(report_rows)

    with open(resampled_qc_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case_id",
                "patient_id",
                "series_uid",
                "folder",
                "consensus_level",
                "original_shape",
                "new_shape",
                "total_voxels_before",
                "total_voxels_after",
                "voxel_count_diff",
                "voxel_change_ratio",
                "qc_major_threshold",
                "qc_status",
            ],
        )
        writer.writeheader()
        writer.writerows(resampled_qc_rows)

    stats["report_csv"] = report_path
    stats["resampled_qc_csv"] = resampled_qc_path
    stats["resampled_qc_rows"] = len(resampled_qc_rows)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare LIDC series folders for nnU-Net v2 segmentation")
    parser.add_argument("input_root", help="Folder containing per-series folders with .nii.gz + .xml")
    parser.add_argument("nnunet_raw_dir", help="Path to nnUNet_raw directory")
    parser.add_argument("--dataset-id", type=int, default=101, help="nnU-Net dataset ID")
    parser.add_argument("--dataset-name", default="LungNodule", help="nnU-Net dataset name suffix")
    parser.add_argument("--consensus-level", type=float, default=0.5, help="pylidc consensus clevel")
    parser.add_argument("--exclude-empty", action="store_true", help="Skip cases with zero nodule voxels")
    parser.add_argument(
        "--non-recursive-search",
        action="store_true",
        help="Only search direct subfolders of input_root for series folders",
    )
    parser.add_argument("--report-name", default="prep_report.csv", help="CSV report file name inside dataset folder")
    parser.add_argument(
        "--resampled-qc-name",
        default="resampled_qc.csv",
        help="CSV file name (inside dataset folder) dedicated to resampled mismatch audit",
    )
    parser.add_argument(
        "--qc-major-threshold",
        type=float,
        default=0.10,
        help="Absolute voxel-change ratio threshold to flag resampled cases as major mismatch",
    )
    parser.add_argument(
        "--disable-shape-resample",
        action="store_true",
        help="Disable nearest-neighbor fallback when consensus mask shape mismatches image region",
    )
    parser.add_argument(
        "--allow-empty-pylidc-db",
        action="store_true",
        help="Continue even if pylidc database has zero scans (not recommended)",
    )
    parser.add_argument("--dicom-root", default=None, help="Original LIDC DICOM root for .pylidcrc")
    parser.add_argument(
        "--create-pylidcrc",
        action="store_true",
        help="Create ~/.pylidcrc automatically if missing",
    )
    args = parser.parse_args()

    ok, msg = ensure_pylidc_config(args.dicom_root, args.create_pylidcrc)
    print(msg)
    if not ok:
        raise SystemExit(1)

    stats = automate_nnunet_prep(
        input_root=args.input_root,
        nnunet_raw_dir=args.nnunet_raw_dir,
        dataset_id=args.dataset_id,
        dataset_name=args.dataset_name,
        consensus_level=args.consensus_level,
        include_empty_cases=not args.exclude_empty,
        report_name=args.report_name,
        resampled_qc_name=args.resampled_qc_name,
        qc_major_change_threshold=args.qc_major_threshold,
        allow_empty_pylidc_db=args.allow_empty_pylidc_db,
        resample_mismatched_masks=not args.disable_shape_resample,
        recursive_search=not args.non_recursive_search,
    )

    print("\nPreparation finished")
    for key, value in stats.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
