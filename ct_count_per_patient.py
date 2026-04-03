#!/usr/bin/env python3
"""
Summarize CT scan count per patient from xml_metadata.csv.

Usage:
  python ct_count_per_patient.py
  python ct_count_per_patient.py --input xml_metadata.csv --output ct_per_patient.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from collections import defaultdict


def count_ct_scans_per_patient(input_csv: Path) -> dict[str, int]:
    """
    Read XML metadata CSV and count CT scans per patient.
    
    Args:
        input_csv: Path to xml_metadata.csv
        
    Returns:
        Dictionary mapping PatientID -> count of CT scans
    """
    ct_count = defaultdict(int)
    
    with input_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Schema") == "CT_XML":
                patient_id = row.get("PatientID", "")
                if patient_id:
                    ct_count[patient_id] += 1
    
    return dict(ct_count)


def export_ct_summary(ct_count: dict[str, int], output_csv: Path) -> None:
    """
    Export CT scan count summary to CSV file.
    
    Args:
        ct_count: Dictionary mapping PatientID -> CT scan count
        output_csv: Path to output CSV file
    """
    # Sort by patient ID for consistency
    sorted_patients = sorted(ct_count.items())
    
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["PatientID", "CT_ScanCount"])
        for patient_id, count in sorted_patients:
            writer.writerow([patient_id, count])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize CT scan count per patient"
    )
    parser.add_argument(
        "--input",
        default="xml_metadata.csv",
        help="Input XML metadata CSV (default: xml_metadata.csv)",
    )
    parser.add_argument(
        "--output",
        default="ct_per_patient.csv",
        help="Output summary CSV (default: ct_per_patient.csv)",
    )
    
    args = parser.parse_args()
    cwd = Path.cwd()
    
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = cwd / input_path
    
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 1
    
    print(f"Reading from: {input_path}")
    ct_count = count_ct_scans_per_patient(input_path)
    
    if not ct_count:
        print("No CT scans found in input CSV")
        return 1
    
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = cwd / output_path
    
    export_ct_summary(ct_count, output_path)
    
    total_patients = len(ct_count)
    total_scans = sum(ct_count.values())
    avg_scans = total_scans / total_patients if total_patients > 0 else 0
    
    print(f"✓ Exported summary to: {output_path}")
    print(f"  Total patients with CT scans: {total_patients}")
    print(f"  Total CT scans: {total_scans}")
    print(f"  Average CT scans per patient: {avg_scans:.2f}")
    
    # Show top 10 patients by CT scan count
    top_10 = sorted(ct_count.items(), key=lambda x: x[1], reverse=True)[:10]
    print("\nTop 10 patients by CT scan count:")
    for patient_id, count in top_10:
        print(f"  {patient_id}: {count} scans")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
