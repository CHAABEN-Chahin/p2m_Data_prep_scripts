#!/usr/bin/env python3
"""
Quick XML viewer for LIDC-IDRI data.

Examples:
  python xml_viewer.py --list 10
  python xml_viewer.py --summary
  python xml_viewer.py --show LIDC-IDRI/LIDC-IDRI-0001/.../069.xml
  python xml_viewer.py --show "LIDC-IDRI/.../069.xml" --max-lines 200
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def local_name(tag: str) -> str:
    """Return tag name without XML namespace."""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def iter_xml_files(root: Path):
    """Yield XML files under root in sorted order."""
    for path in sorted(root.rglob("*.xml")):
        yield path


def parse_xml(path: Path):
    """Parse XML and return root element or None on parse failure."""
    try:
        tree = ET.parse(path)
        return tree.getroot()
    except ET.ParseError:
        return None


def text_of(parent: ET.Element, tag_name: str) -> str:
    """Get first child text by local tag name."""
    for child in parent.iter():
        if local_name(child.tag) == tag_name:
            return (child.text or "").strip()
    return ""


def detect_schema(root_elem: ET.Element | None) -> str:
    if root_elem is None:
        return "INVALID_XML"
    name = local_name(root_elem.tag)
    if name == "LidcReadMessage":
        return "CT_XML"
    if name == "IdriReadMessage":
        return "CXR_XML"
    return f"UNKNOWN({name})"


def count_tags(root_elem: ET.Element | None, tag_name: str) -> int:
    if root_elem is None:
        return 0
    return sum(1 for e in root_elem.iter() if local_name(e.tag) == tag_name)


def short_summary(path: Path, rel_base: Path) -> str:
    root_elem = parse_xml(path)
    schema = detect_schema(root_elem)

    if root_elem is None:
        return f"{path.relative_to(rel_base)} | INVALID_XML"

    study_uid = text_of(root_elem, "StudyInstanceUID")
    series_uid = text_of(root_elem, "SeriesInstanceUid") or text_of(root_elem, "SeriesInstanceUID")
    if not series_uid:
        # CXR flavor often stores CXRSeriesInstanceUid
        series_uid = text_of(root_elem, "CXRSeriesInstanceUid")

    if schema == "CT_XML":
        sessions = count_tags(root_elem, "readingSession")
        nodules = count_tags(root_elem, "unblindedReadNodule")
        non_nodules = count_tags(root_elem, "nonNodule")
        return (
            f"{path.relative_to(rel_base)} | {schema} | sessions={sessions} "
            f"nodules={nodules} nonNodules={non_nodules} "
            f"seriesUID={series_uid[:24]}..."
        )

    if schema == "CXR_XML":
        sessions = count_tags(root_elem, "CXRreadingSession")
        reads = count_tags(root_elem, "unblindedRead")
        return (
            f"{path.relative_to(rel_base)} | {schema} | sessions={sessions} "
            f"reads={reads} seriesUID={series_uid[:24]}..."
        )

    return (
        f"{path.relative_to(rel_base)} | {schema} | "
        f"studyUID={study_uid[:24]}... seriesUID={series_uid[:24]}..."
    )


def print_file_with_numbers(path: Path, max_lines: int) -> None:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f, start=1):
            if idx > max_lines:
                print(f"... truncated at {max_lines} lines")
                break
            print(f"{idx:5d}: {line.rstrip()}")


def overall_summary(xml_paths: list[Path], rel_base: Path) -> None:
    total = len(xml_paths)
    ct = 0
    cxr = 0
    invalid = 0
    unknown = 0

    for path in xml_paths:
        root_elem = parse_xml(path)
        schema = detect_schema(root_elem)
        if schema == "CT_XML":
            ct += 1
        elif schema == "CXR_XML":
            cxr += 1
        elif schema == "INVALID_XML":
            invalid += 1
        else:
            unknown += 1

    print(f"Root: {rel_base}")
    print(f"Total XML files: {total}")
    print(f"CT XML (LidcReadMessage): {ct}")
    print(f"CXR XML (IdriReadMessage): {cxr}")
    print(f"Unknown schema: {unknown}")
    print(f"Invalid XML: {invalid}")


def resolve_show_path(show_arg: str, cwd: Path) -> Path:
    p = Path(show_arg)
    if p.is_absolute():
        return p
    return (cwd / p).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="View and summarize LIDC-IDRI XML files")
    parser.add_argument(
        "--root",
        default="LIDC-IDRI",
        help="Root folder to scan for XML files (default: LIDC-IDRI)",
    )
    parser.add_argument(
        "--list",
        type=int,
        default=0,
        help="List first N XML files with short summaries",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print overall XML schema summary",
    )
    parser.add_argument(
        "--show",
        default="",
        help="Show one XML file with line numbers (relative or absolute path)",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=150,
        help="Maximum lines to print when using --show (default: 150)",
    )

    args = parser.parse_args()
    cwd = Path.cwd()

    if args.show:
        show_path = resolve_show_path(args.show, cwd)
        if not show_path.exists():
            print(f"File not found: {show_path}")
            return 1
        print(f"Showing: {show_path}")
        print_file_with_numbers(show_path, max_lines=max(1, args.max_lines))
        return 0

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

    if args.summary:
        overall_summary(xml_paths, root)

    if args.list > 0:
        limit = min(args.list, len(xml_paths))
        print(f"Listing {limit} of {len(xml_paths)} XML files:\n")
        for path in xml_paths[:limit]:
            print(short_summary(path, root))

    if not args.summary and args.list <= 0:
        print("No action selected.")
        print("Try one of:")
        print("  --summary")
        print("  --list 10")
        print("  --show <path-to-xml>")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
