import argparse
import os
import re
import shutil
from tqdm import tqdm

from reconstruct_3d_volume import reconstruct_native_geometry


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def _copy_series_xml_files(series_path: str, out_series_dir: str) -> int:
    """Copy XML annotation files from a source series folder to output folder."""
    copied = 0
    for name in sorted(os.listdir(series_path)):
        if not name.lower().endswith(".xml"):
            continue
        src = os.path.join(series_path, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(out_series_dir, name)
        shutil.copy2(src, dst)
        copied += 1
    return copied


def batch_reconstruct_lidc(
    root_dir: str,
    output_dir: str,
    min_slices: int = 50,
    hu_min: int = -1000,
    hu_max: int = 400,
    overwrite: bool = False,
) -> dict:
    """Crawl the LIDC-IDRI hierarchy and reconstruct valid CT series into NIfTI files."""
    if not os.path.isdir(root_dir):
        raise FileNotFoundError(f"Input root not found: {root_dir}")

    os.makedirs(output_dir, exist_ok=True)

    stats = {
        "patients": 0,
        "series_seen": 0,
        "saved": 0,
        "xml_copied": 0,
        "skipped_existing": 0,
        "skipped_other": 0,
    }

    patient_folders = sorted(
        f
        for f in os.listdir(root_dir)
        if f.startswith("LIDC-IDRI-") and os.path.isdir(os.path.join(root_dir, f))
    )
    stats["patients"] = len(patient_folders)

    for patient_id in tqdm(patient_folders, desc="Processing patients"):
        patient_path = os.path.join(root_dir, patient_id)

        for study_folder in sorted(os.listdir(patient_path)):
            study_path = os.path.join(patient_path, study_folder)
            if not os.path.isdir(study_path):
                continue

            for series_folder in sorted(os.listdir(study_path)):
                series_path = os.path.join(study_path, series_folder)
                if not os.path.isdir(series_path):
                    continue

                stats["series_seen"] += 1

                out_series_dir = os.path.join(
                    output_dir,
                    _safe_name(patient_id),
                    _safe_name(study_folder),
                    _safe_name(series_folder),
                )
                output_path = os.path.join(out_series_dir, f"{_safe_name(patient_id)}_native.nii.gz")
                os.makedirs(out_series_dir, exist_ok=True)

                if (not overwrite) and os.path.exists(output_path):
                    stats["xml_copied"] += _copy_series_xml_files(series_path, out_series_dir)
                    stats["skipped_existing"] += 1
                    continue

                ok, _message, _size_xyz, _spacing_xyz = reconstruct_native_geometry(
                    series_folder_path=series_path,
                    output_path=output_path,
                    min_slices=min_slices,
                    hu_min=hu_min,
                    hu_max=hu_max,
                    verbose=False,
                )

                if ok:
                    stats["xml_copied"] += _copy_series_xml_files(series_path, out_series_dir)
                    stats["saved"] += 1
                else:
                    stats["skipped_other"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-reconstruct LIDC-IDRI CT series into NIfTI.")
    parser.add_argument("root_dir", help="Path to LIDC-IDRI root directory")
    parser.add_argument("output_dir", help="Folder where per-series output folders will be written")
    parser.add_argument("--min-slices", type=int, default=50, help="Minimum DICOM slices to accept")
    parser.add_argument("--hu-min", type=int, default=-1000, help="Lower HU clip bound")
    parser.add_argument("--hu-max", type=int, default=400, help="Upper HU clip bound")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    args = parser.parse_args()

    stats = batch_reconstruct_lidc(
        root_dir=args.root_dir,
        output_dir=args.output_dir,
        min_slices=args.min_slices,
        hu_min=args.hu_min,
        hu_max=args.hu_max,
        overwrite=args.overwrite,
    )

    print("\nBatch reconstruction finished")
    print(f"Patients found:         {stats['patients']}")
    print(f"Series visited:         {stats['series_seen']}")
    print(f"Volumes saved:          {stats['saved']}")
    print(f"XML files copied:       {stats['xml_copied']}")
    print(f"Skipped existing files: {stats['skipped_existing']}")
    print(f"Skipped other reasons:  {stats['skipped_other']}")


if __name__ == "__main__":
    main()