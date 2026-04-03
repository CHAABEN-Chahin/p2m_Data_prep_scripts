# nnU-Net v2 Preparation Guide (LIDC-IDRI)

This guide explains, from zero, how to prepare your LIDC-IDRI data for nnU-Net v2 segmentation using the automation script.

It covers:
- What the script does
- What you must set up first
- How to run it
- What files are created
- What warnings to watch for before training

## 1. Goal

You have per-series folders that contain:
- one CT image volume: `.nii.gz`
- one XML annotation file: `.xml`

You want a valid nnU-Net v2 dataset folder with:
- `imagesTr/`
- `labelsTr/`
- `dataset.json`

The script also creates audit reports so you can trust what happened to each case.

## 2. What the Automation Script Does

Script: `prepare_nnunet_lidc.py`

For each series folder, it does:
1. Finds NIfTI + XML.
2. Reads `SeriesInstanceUid` from XML.
3. Queries `pylidc` database to find the matching scan.
4. Builds a binary nodule mask from consensus annotations (`clevel`, default 0.5).
5. Handles shape mismatch safely:
   - Either skip mismatch
   - Or resample mask using **nearest neighbor only** (label-safe)
6. Saves nnU-Net files:
   - image -> `imagesTr/<case_id>_0000.nii.gz`
   - label -> `labelsTr/<case_id>.nii.gz`
7. Writes metadata:
   - `dataset.json`
8. Writes reports:
   - `prep_report.csv` (all cases)
   - `resampled_qc.csv` (only resampled mismatch events)

## 3. Required Setup

## 3.1 Python environment

Use your workspace virtual environment.

PowerShell:
```powershell
& d:\DATA\manifest-1600709154662\.venv\Scripts\Activate.ps1
```

Install dependencies:
```powershell
python -m pip install -r requirements.txt
```

Important dependency note:
- `pylidc` currently needs `pkg_resources`, so `setuptools<81` is pinned in `requirements.txt`.

## 3.2 Configure pylidc (`.pylidcrc`)

`pylidc` needs a config in your home directory:
- Windows location example: `C:\Users\<YourUser>\.pylidcrc`

Content:
```ini
[DICOM]
path = d:/DATA/manifest-1600709154662/LIDC-IDRI
warn = False
```

You can let the script create it automatically using:
- `--dicom-root ...`
- `--create-pylidcrc`

## 3.3 pylidc database must be indexed

The script checks if `pylidc` has scans indexed.
If scan count is 0, it stops (unless you force override).

Why this matters:
- No scan index -> no UID match -> most/all cases skipped.

## 4. Input Data Expectations

`input_root` must contain folders like:
- `<series_folder_1>/image.nii.gz + annotation.xml`
- `<series_folder_2>/image.nii.gz + annotation.xml`

If either file is missing, case is skipped and logged in `prep_report.csv`.

## 5. Basic Run Command

```powershell
python prepare_nnunet_lidc.py "D:/PATH/TO/SERIES_ROOT" "D:/PATH/TO/nnUNet_raw" \
  --dataset-id 101 \
  --dataset-name LungNodule \
  --dicom-root "d:/DATA/manifest-1600709154662/LIDC-IDRI" \
  --create-pylidcrc
```

This creates:
- `D:/PATH/TO/nnUNet_raw/Dataset101_LungNodule/imagesTr`
- `D:/PATH/TO/nnUNet_raw/Dataset101_LungNodule/labelsTr`
- `D:/PATH/TO/nnUNet_raw/Dataset101_LungNodule/dataset.json`
- `D:/PATH/TO/nnUNet_raw/Dataset101_LungNodule/prep_report.csv`
- `D:/PATH/TO/nnUNet_raw/Dataset101_LungNodule/resampled_qc.csv`

## 6. Important CLI Options

- `--dataset-id`: nnU-Net dataset number (default `101`)
- `--dataset-name`: name suffix (default `LungNodule`)
- `--consensus-level`: pylidc `clevel` (default `0.5`)
- `--exclude-empty`: skip cases with empty masks
- `--report-name`: full report filename (default `prep_report.csv`)
- `--resampled-qc-name`: resample-only QC report (default `resampled_qc.csv`)
- `--qc-major-threshold`: fail threshold for voxel change ratio (default `0.10`)
- `--disable-shape-resample`: disable fallback resampling and skip mismatches
- `--allow-empty-pylidc-db`: continue even if DB has 0 scans (not recommended)
- `--dicom-root`: DICOM root used for `.pylidcrc`
- `--create-pylidcrc`: create `.pylidcrc` automatically if missing

## 7. Reports and How to Use Them

## 7.1 `prep_report.csv` (all cases)

Main columns:
- `status`: `processed` / `skipped` / `error`
- `reason`: why skipped or failed
- `mask_resampled`: `1` if mismatch resampling used
- `nodule_voxels`: final positive voxels in mask

Use this file to answer:
- How many cases were actually prepared?
- Why were cases skipped?

## 7.2 `resampled_qc.csv` (resampled-only events)

Main columns:
- `original_shape`
- `new_shape`
- `total_voxels_before`
- `total_voxels_after`
- `voxel_change_ratio`
- `qc_status` (`PASS (Minor)` or `FAIL (Major Mismatch)`)

Use this file for quick QC:
- Open only these flagged/resampled cases in 3D viewer (Slicer/ITK-SNAP)
- Review major mismatches first

## 8. Critical Cautions Before Training

1. Nearest-neighbor is mandatory for label resampling.
- Never use linear/cubic interpolation for masks.

2. Resampled masks may still be geometrically imperfect.
- Even with nearest-neighbor, if source and target geometry differ a lot, alignment may be off.

3. Always check `resampled_qc.csv` before training.
- Especially rows with `FAIL (Major Mismatch)`.

4. Do not trust silent pipelines.
- Keep both reports with experiment logs for reproducibility.

5. Keep image-label pairing consistent.
- Same `case_id` must exist in both `imagesTr` and `labelsTr`.

## 9. Recommended Workflow (Safe)

1. Run script with default safe options.
2. Inspect `prep_report.csv` summary counts.
3. Filter `resampled_qc.csv` for major mismatches.
4. Visually inspect flagged cases in 3D viewer.
5. Remove bad cases if needed.
6. Train nnU-Net v2.
7. Document how many cases were processed/skipped/resampled.

## 10. Troubleshooting

### Problem: "pylidc database contains 0 scans"
- Check `.pylidcrc` path points to real LIDC DICOM root.
- Ensure pylidc indexing is available in your environment.
- Use `--allow-empty-pylidc-db` only for debugging, not production.

### Problem: Many "no matching scan in pylidc database"
- Usually UID mismatch or wrong DICOM root in `.pylidcrc`.
- Confirm XML SeriesInstanceUid corresponds to DICOM indexed by pylidc.

### Problem: Too many major mismatches in `resampled_qc.csv`
- Revisit earlier CT reconstruction pipeline.
- Prefer preserving original geometry when generating NIfTI from DICOM.

### Problem: nnU-Net does not see cases
- Verify filenames:
  - images: `<case_id>_0000.nii.gz`
  - labels: `<case_id>.nii.gz`
- Verify `dataset.json` exists and `numTraining` is correct.

## 11. One Practical Example

```powershell
python prepare_nnunet_lidc.py "D:/DATA/series_ready" "D:/DATA/nnUNet_raw" \
  --dataset-id 101 \
  --dataset-name LungNodule \
  --consensus-level 0.5 \
  --qc-major-threshold 0.10 \
  --dicom-root "d:/DATA/manifest-1600709154662/LIDC-IDRI" \
  --create-pylidcrc
```

Then review:
- `D:/DATA/nnUNet_raw/Dataset101_LungNodule/prep_report.csv`
- `D:/DATA/nnUNet_raw/Dataset101_LungNodule/resampled_qc.csv`

---

If you want, the next step is to add a tiny "post-check" script that verifies every `imagesTr` case has a matching `labelsTr` case and prints a final dataset health score.
