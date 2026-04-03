import csv
import os
import re
import xml.etree.ElementTree as ET

ROOT = r"d:\DATA\manifest-1600709154662"
CSV_IN = os.path.join(ROOT, "ct_slices_per_series.csv")
DICOM_ROOT = os.path.join(ROOT, "LIDC-IDRI")
OUT_ROOT = os.path.join(ROOT, "outputs_native_full")
CSV_OUT = os.path.join(ROOT, "suspicious_missing_native_min50.csv")

MIN_SLICES = 50

def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")

def is_ct_xml(series_path: str):
    xmls = [f for f in os.listdir(series_path) if f.lower().endswith(".xml")]
    if not xmls:
        return False, "no_xml"
    xml_path = os.path.join(series_path, xmls[0])
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return False, "bad_xml"
    if "LidcReadMessage" in root.tag:
        return True, "ct_xml"
    return False, "non_ct_xml"

rows_out = []
with open(CSV_IN, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        patient = row["PatientID"]
        study = row["Study"]
        series = row["Series"]
        slices = int(row["SliceCount"])

        if slices < MIN_SLICES:
            continue

        series_path = os.path.join(DICOM_ROOT, patient, study, series)
        out_nii = os.path.join(
            OUT_ROOT,
            safe_name(patient),
            safe_name(study),
            safe_name(series),
            f"{safe_name(patient)}_native.nii.gz",
        )

        if os.path.exists(out_nii):
            continue

        ct_ok, ct_reason = is_ct_xml(series_path) if os.path.isdir(series_path) else (False, "missing_series_dir")
        rows_out.append({
            "PatientID": patient,
            "Study": study,
            "Series": series,
            "SliceCount": slices,
            "SeriesPath": series_path,
            "ExpectedOutputNii": out_nii,
            "CT_XML_OK": int(ct_ok),
            "XML_Check": ct_reason,
        })

with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "PatientID", "Study", "Series", "SliceCount",
            "SeriesPath", "ExpectedOutputNii",
            "CT_XML_OK", "XML_Check"
        ],
    )
    writer.writeheader()
    writer.writerows(rows_out)

print("Wrote:", CSV_OUT)
print("Suspicious missing (slice>=50):", len(rows_out))
print("CT-XML suspicious subset:", sum(1 for r in rows_out if r["CT_XML_OK"] == 1))