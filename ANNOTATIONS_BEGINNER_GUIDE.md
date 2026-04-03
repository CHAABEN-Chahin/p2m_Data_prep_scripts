# LIDC-IDRI Annotations: Beginner Guide

If you feel lost with annotations, this file is for you.

This guide explains:
- what annotation files are
- why you have 2 annotation formats
- what each important field means
- how to read one file from start to finish
- how to connect annotation XML to your 3D output volume

## 1) What an annotation is

An annotation is a radiologist note saved in XML.

In your dataset, each series folder usually contains:
- image files (.dcm)
- one XML annotation file

The XML tells you what doctors marked (nodules, non-nodules, contours, ratings).

## 2) You have 2 different XML schemas

Your dataset mixes CT and chest X-ray (CXR). That is normal in LIDC-IDRI.

### A) CT annotation XML

CT annotation XML has root tag:
- LidcReadMessage

These are the files used for 3D nodule work.

Main structure:
- readingSession (one reader session)
- unblindedReadNodule (a nodule candidate)
- nonNodule (finding judged not a nodule)
- roi (region on a slice)
- edgeMap (x, y contour points)

### B) CXR annotation XML

CXR annotation XML has root tag:
- IdriReadMessage

These are chest X-ray annotations, not CT volume contours.

Main structure:
- CXRreadingSession
- unblindedRead
- roi
- edgeMap

## 3) Fast way to classify any XML

Open first lines of the XML:
- if root is LidcReadMessage -> CT annotation
- if root is IdriReadMessage -> CXR annotation

Only CT annotations are typically useful for your 3D CT volume reconstruction pipeline.

## 4) Important tags you will see (plain language)

### Common identity tags

- StudyInstanceUID:
  Study identifier.

- SeriesInstanceUid (or CXRSeriesInstanceUid):
  Series identifier.
  This is the key for matching XML with DICOM series metadata.

- imageSOP_UID:
  Exact image slice UID.

### CT lesion tags

- readingSession:
  One radiologist review session.

- unblindedReadNodule:
  A nodule marked by a reader.

- noduleID:
  Reader-specific nodule ID.

- characteristics:
  Reader scores for lesion appearance.

Common characteristic fields and rough meaning:
- subtlety: how obvious it is
- sphericity: how round it is
- margin: border sharpness
- lobulation: lobulated shape level
- spiculation: spike-like edges
- texture: internal appearance
- malignancy: reader suspicion level

- roi:
  Nodule outline information on one slice.

- imageZposition:
  Slice position in z direction.

- inclusion:
  Whether contour includes lesion boundary.

- edgeMap with xCoord and yCoord:
  Polygon points for that lesion on that slice.

### CT non-lesion tags

- nonNodule:
  A marked finding that is not considered a true nodule.

### CXR tags

- CXRreadingSession:
  Reader session for CXR.

- unblindedRead:
  One CXR finding.

- characteristics:
  Often includes confidence, subtlety, obscuration, and reason.

## 5) Why one patient can look confusing

You may see multiple markings for the same physical lesion because:
- there are multiple readers
- each reader can draw slightly different contours
- nodules can span many slices, so one nodule has many roi blocks

So one lesion is not always one simple row.

## 6) What "good" CT annotation coverage looks like

For a CT series, you usually want:
- XML schema = CT (LidcReadMessage)
- one or more readingSession
- at least some unblindedReadNodule
- roi blocks containing edgeMap points

If there are only nonNodule entries, that series may still be valid but has no positive nodule contour target.

## 7) How annotation links to your reconstructed output

Your patched batch output now creates:
- output_root/patient/study/series/volume.nii.gz
- output_root/patient/study/series/<xml file copied>

This is the easiest mapping because volume and source XML are in the same folder.

For robust programmatic matching, also use UID fields:
- XML SeriesInstanceUid <-> DICOM series UID
- XML imageSOP_UID <-> DICOM slice SOP UID

## 8) Practical interpretation workflow (recommended)

When inspecting one case:
1. Confirm it is CT XML (LidcReadMessage).
2. Read StudyInstanceUID and SeriesInstanceUid.
3. Count readingSession blocks.
4. For each unblindedReadNodule:
   - read noduleID
   - inspect characteristics
   - count how many roi slices exist
5. For each roi:
   - read imageSOP_UID and imageZposition
   - collect edgeMap points as contour polygon
6. Keep reader identity separate if you want reader-wise analysis.

## 9) Minimal glossary

- UID: unique identifier string in DICOM world.
- Series: one scan acquisition (stack of images).
- SOP Instance UID: unique ID for one DICOM image.
- ROI: region of interest (contour on one slice).
- Nodule: suspected lung lesion.
- NonNodule: marked region not considered a true nodule.

## 10) If you want next step automation

A useful next script would produce one flat CSV/JSON per CT nodule with:
- patient_id
- study_uid
- series_uid
- reader_session_index
- nodule_id
- slice_sop_uid
- z_position
- contour_points
- characteristics scores

That makes training or analysis much easier than raw XML.
