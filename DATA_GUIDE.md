# LIDC-IDRI Data Organization Guide

This guide explains how your local dataset is organized and what each XML file means.

## 1) What is in this folder

At the top level you have:

- `LIDC-IDRI/`: patient folders and image/annotation files
- `metadata.csv`: series-level metadata export (from the download manifest)
- `display.py`: a simple DICOM visualization script
- `ct_slice_preview.png`: output image from the script

From quick inspection:

- Total annotation XML files: **1180**
- CT-style XML files (`LidcReadMessage`): **930**
- CXR-style XML files (`IdriReadMessage`): **250**

## 2) Folder hierarchy (how to read paths)

A typical path looks like this:

`LIDC-IDRI/LIDC-IDRI-0001/01-01-2000-NA-NA-30178/3000566.000000-NA-03192/`

Levels mean:

1. `LIDC-IDRI-0001`: patient/subject ID
2. `01-01-2000-...`: study folder
3. `3000566.000000-...`: series folder
4. inside series folder:
   - many `.dcm` files = image slices (or x-ray images)
   - one `.xml` file = radiologist annotation/read for that series

So, practically: **one series folder = images + one XML describing findings/readouts**.

## 3) There are 2 XML formats in your data

Your dataset mixes CT and chest X-ray reads, and that is why XML files look different.

### A) CT annotation XML

Root tag:

`<LidcReadMessage ... xmlns="http://www.nih.gov">`

Common header fields:

- `TaskDescription`: usually `Second unblinded read`
- `SeriesInstanceUid`: DICOM Series UID this XML belongs to
- `StudyInstanceUID`: DICOM Study UID

Main body pattern:

- multiple `<readingSession>` blocks (usually one per radiologist)
- each session can contain:
  - `<unblindedReadNodule>`: a candidate nodule
  - `<nonNodule>`: marked finding considered not a nodule

Inside a CT nodule:

- `noduleID`: reader-specific ID
- `characteristics` (optional but common):
  - `subtlety`, `internalStructure`, `calcification`, `sphericity`,
    `margin`, `lobulation`, `spiculation`, `texture`, `malignancy`
- one or more `<roi>` blocks:
  - `imageSOP_UID`: exact DICOM slice/image UID
  - `imageZposition`: z coordinate of that slice
  - `inclusion`: if contour is inclusive (usually TRUE)
  - many `<edgeMap>` points (`xCoord`, `yCoord`) forming contour/polygon

Meaning:

- A CT nodule can span multiple slices, so one nodule can have multiple ROIs.
- Different radiologists can mark the same physical lesion differently.

### B) CXR annotation XML

Root tag:

`<IdriReadMessage ... xmlns="http://www.nih.gov/idri">`

Common header fields:

- `TaskDescription`: often `CXR read`
- `CTSeriesInstanceUid` and `CXRSeriesInstanceUid`
- `Modality`: `CXR`

Main body pattern:

- multiple `<CXRreadingSession>` blocks (again, one per reader)
- each session has `<unblindedRead>` items

Inside CXR read:

- `noduleID`
- `characteristics` with CXR-specific fields such as:
  - `confidence`, `subtlety`, `obscuration`, sometimes `reason`
- `roi` with `imageSOP_UID` and one/few `edgeMap` points

Meaning:

- These are chest x-ray annotations, not CT slice contours.
- Coordinate behavior and attributes differ from CT XML.

## 4) How XML links to DICOM files

Use these IDs for reliable matching:

- XML `SeriesInstanceUid` (or `CXRSeriesInstanceUid`) <-> DICOM series UID
- XML `imageSOP_UID` <-> DICOM SOP Instance UID (specific image)

In your folders this is already organized physically (XML sits with matching DICOM files), but UID matching is the robust way when you build code.

## 5) Why things may feel confusing

1. Mixed modalities in same dataset
   - You have CT, DX, and CR series.
   - XML is present for both CT (`LidcReadMessage`) and CXR (`IdriReadMessage`) reads.

2. Multiple readers per case
   - Same lesion may appear multiple times across `readingSession` blocks.

3. Different XML schemas
   - CT schema and CXR schema use different field names and structures.

4. `metadata.csv` parsing pitfalls
   - The file contains comma-separated text, but some values (for example file sizes) also include commas, so naive CSV parsing can shift columns.
   - If you use `metadata.csv` in code, validate columns carefully before relying on `File Location` and numeric fields.

## 6) Practical workflow recommendation

If your goal is lung nodule CT analysis:

1. Keep only series whose XML root is `LidcReadMessage`.
2. For each CT nodule (`unblindedReadNodule`), collect all ROI contours across slices.
3. Decide how to combine multiple readers (consensus or per-reader modeling).
4. Ignore `IdriReadMessage` files unless you also want chest x-ray tasks.

If your goal includes CXR:

1. Process `IdriReadMessage` separately.
2. Use CXR-specific fields (`confidence`, `obscuration`, etc.).

## 7) Quick visual check method

When opening a random XML, first read only the first 2-3 lines:

- `<LidcReadMessage` -> CT annotation
- `<IdriReadMessage` -> CXR annotation

Then inspect `TaskDescription` and `SeriesInstanceUid` to confirm context.

---

If you want, I can next create a small parser script that:

- auto-detects CT vs CXR XML
- prints a clean summary per file
- exports one normalized CSV with key fields
