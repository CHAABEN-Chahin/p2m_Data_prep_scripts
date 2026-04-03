import argparse
import os
from typing import Tuple
import SimpleITK as sitk
import xml.etree.ElementTree as ET


def _is_ct_series_from_xml(series_folder_path: str) -> Tuple[bool, str]:
    xml_files = [f for f in os.listdir(series_folder_path) if f.lower().endswith(".xml")]
    if not xml_files:
        return False, "no XML found"

    xml_path = os.path.join(series_folder_path, xml_files[0])
    try:
        root = ET.parse(xml_path).getroot()
    except Exception as exc:
        return False, f"invalid XML ({exc})"

    if "LidcReadMessage" not in root.tag:
        return False, "not CT XML (likely CXR/X-ray)"

    return True, "ok"


def reconstruct_native_geometry(
    series_folder_path: str,
    output_path: str,
    min_slices: int = 50,
    hu_min: int = -1000,
    hu_max: int = 400,
    verbose: bool = True,
) -> Tuple[bool, str, Tuple[int, int, int], Tuple[float, float, float]]:
    """Reconstruct CT series in native geometry (no resampling) and save as NIfTI."""
    if not os.path.isdir(series_folder_path):
        return False, f"series folder not found: {series_folder_path}", (0, 0, 0), (0.0, 0.0, 0.0)

    is_ct, reason = _is_ct_series_from_xml(series_folder_path)
    if not is_ct:
        return False, f"skipped: {reason}", (0, 0, 0), (0.0, 0.0, 0.0)

    try:
        dicom_names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(series_folder_path)
    except Exception as exc:
        return False, f"failed reading DICOM file names ({exc})", (0, 0, 0), (0.0, 0.0, 0.0)

    if len(dicom_names) < min_slices:
        return False, f"skipped: only {len(dicom_names)} slices (< {min_slices})", (0, 0, 0), (0.0, 0.0, 0.0)

    try:
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(dicom_names)
        image = reader.Execute()

        # Clip intensities while preserving native scanner geometry.
        image = sitk.IntensityWindowing(image, hu_min, hu_max, hu_min, hu_max)
        final_volume = sitk.Cast(image, sitk.sitkInt16)

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        sitk.WriteImage(final_volume, output_path)
        size_xyz = tuple(int(v) for v in final_volume.GetSize())
        spacing_xyz = tuple(float(v) for v in final_volume.GetSpacing())
    except Exception as exc:
        return False, f"failed reconstruction ({exc})", (0, 0, 0), (0.0, 0.0, 0.0)

    if verbose:
        print(f"Success: {output_path} | slices={len(dicom_names)} | size={size_xyz} | spacing={spacing_xyz}")
    return True, "saved", size_xyz, spacing_xyz


def reconstruct_3d_series(
    series_folder_path: str,
    output_path: str,
    min_slices: int = 50,
    hu_min: int = -1000,
    hu_max: int = 400,
    target_spacing: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    verbose: bool = True,
) -> Tuple[bool, str]:
    """Backward-compatible wrapper; target_spacing is ignored in native mode."""
    _ = target_spacing
    ok, message, _, _ = reconstruct_native_geometry(
        series_folder_path=series_folder_path,
        output_path=output_path,
        min_slices=min_slices,
        hu_min=hu_min,
        hu_max=hu_max,
        verbose=verbose,
    )
    return ok, message


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruct one CT series folder into 3D NIfTI.")
    parser.add_argument("series_folder", help="Path to one series folder containing DICOM + XML")
    parser.add_argument("output_file", help="Output .nii.gz path")
    parser.add_argument("--min-slices", type=int, default=50, help="Minimum DICOM slices to accept")
    parser.add_argument("--hu-min", type=int, default=-1000, help="Lower HU clip bound")
    parser.add_argument("--hu-max", type=int, default=400, help="Upper HU clip bound")
    args = parser.parse_args()

    ok, message, _, _ = reconstruct_native_geometry(
        series_folder_path=args.series_folder,
        output_path=args.output_file,
        min_slices=args.min_slices,
        hu_min=args.hu_min,
        hu_max=args.hu_max,
    )
    print(message)


if __name__ == "__main__":
    main()