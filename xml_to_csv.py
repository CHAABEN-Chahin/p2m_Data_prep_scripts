#!/usr/bin/env python3
"""
Export LIDC-IDRI XML metadata to CSV.

Usage:
  python xml_to_csv.py
  python xml_to_csv.py --output my_data.csv
  python xml_to_csv.py --root LIDC-IDRI --output results.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def local_name(tag: str) -> str:
    """Return tag name without XML namespace."""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def text_of(parent: ET.Element | None, tag_name: str) -> str:
    """Get first child text by local tag name."""
    if parent is None:
        return ""
    for child in parent.iter():
        if local_name(child.tag) == tag_name:
            return (child.text or "").strip()
    return ""


def count_tags(root_elem: ET.Element | None, tag_name: str) -> int:
    if root_elem is None:
        return 0
    return sum(1 for e in root_elem.iter() if local_name(e.tag) == tag_name)


def detect_schema(root_elem: ET.Element | None) -> str:
    if root_elem is None:
        return "INVALID_XML"
    name = local_name(root_elem.tag)
    if name == "LidcReadMessage":
        return "CT_XML"
    if name == "IdriReadMessage":
        return "CXR_XML"
    return f"UNKNOWN({name})"


def parse_xml(path: Path) -> ET.Element | None:
    """Parse XML and return root element or None on parse failure."""
    try:
        tree = ET.parse(path)
        return tree.getroot()
    except ET.ParseError:
        return None


def extract_row(path: Path, rel_base: Path) -> dict:
    """Extract one row of data from an XML file."""
    root_elem = parse_xml(path)
    schema = detect_schema(root_elem)
    rel_path = path.relative_to(rel_base)
    patient_id = rel_path.parts[0] if len(rel_path.parts) > 0 else ""

    row = {
        "File": str(rel_path),
        "PatientID": patient_id,
        "Schema": schema,
        "StudyInstanceUID": text_of(root_elem, "StudyInstanceUID"),
        "SeriesInstanceUid": text_of(root_elem, "SeriesInstanceUid") or text_of(root_elem, "CXRSeriesInstanceUid"),
        "TaskDescription": text_of(root_elem, "TaskDescription"),
        "Modality": text_of(root_elem, "Modality"),
        "DateService": text_of(root_elem, "DateService"),
        "TimeService": text_of(root_elem, "TimeService"),
    }

    if schema == "CT_XML":
        row.update({
            "ReadingSessions": count_tags(root_elem, "readingSession"),
            "Nodules": count_tags(root_elem, "unblindedReadNodule"),
            "NonNodules": count_tags(root_elem, "nonNodule"),
            "CXRSessions": "",
            "CXRReads": "",
        })
    elif schema == "CXR_XML":
        row.update({
            "ReadingSessions": count_tags(root_elem, "CXRreadingSession"),
            "Nodules": "",
            "NonNodules": "",
            "CXRSessions": count_tags(root_elem, "CXRreadingSession"),
            "CXRReads": count_tags(root_elem, "unblindedRead"),
        })
    else:
        row.update({
            "ReadingSessions": "",
            "Nodules": "",
            "NonNodules": "",
            "CXRSessions": "",
            "CXRReads": "",
        })

    return row


def iter_xml_files(root: Path):
    """Yield XML files under root in sorted order."""
    for path in sorted(root.rglob("*.xml")):
        yield path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export LIDC-IDRI XML metadata to CSV"
    )
    parser.add_argument(
        "--root",
        default="LIDC-IDRI",
        help="Root folder to scan for XML files (default: LIDC-IDRI)",
    )
    parser.add_argument(
        "--output",
        default="xml_metadata.csv",
        help="Output CSV filename (default: xml_metadata.csv)",
    )

    args = parser.parse_args()
    cwd = Path.cwd()

    root = Path(args.root)
    if not root.is_absolute():
        root = (cwd / root).resolve()

    if not root.exists():
        print(f"Root not found: {root}")
        return 1

    xml_paths = list(iter_xml_files(root))
    if not xml_paths:
        print(f"No XML files found under: {root}")
        return 1

    print(f"Processing {len(xml_paths)} XML files...")

    rows = [extract_row(path, root) for path in xml_paths]

    fieldnames = [
        "File",
        "PatientID",
        "Schema",
        "StudyInstanceUID",
        "SeriesInstanceUid",
        "TaskDescription",
        "Modality",
        "DateService",
        "TimeService",
        "ReadingSessions",
        "Nodules",
        "NonNodules",
        "CXRSessions",
        "CXRReads",
    ]

    output_path = cwd / args.output
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} rows to: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
