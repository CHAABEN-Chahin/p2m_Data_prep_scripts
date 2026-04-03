#!/usr/bin/env python3
"""
Count DICOM slices per CT imaging series for each patient.
Creates a CSV with PatientID, Study, Series, and SliceCount.
"""

import csv
import os
from pathlib import Path
from collections import defaultdict


def count_slices_per_series(lidc_root="LIDC-IDRI"):
    """
    Count DICOM slices in each CT imaging series.
    
    Args:
        lidc_root: Path to LIDC-IDRI root folder
        
    Returns:
        List of dicts with PatientID, Study, Series, SliceCount
    """
    results = []
    lidc_path = Path(lidc_root)
    
    # Iterate through patient folders
    for patient_folder in sorted(lidc_path.glob("LIDC-IDRI-*")):
        if not patient_folder.is_dir():
            continue
        patient_id = patient_folder.name
        
        # Iterate through study folders (date-based)
        for study_folder in sorted(patient_folder.iterdir()):
            if not study_folder.is_dir():
                continue
            
            study_name = study_folder.name
            
            # Iterate through series folders
            for series_folder in sorted(study_folder.iterdir()):
                if not series_folder.is_dir():
                    continue
                
                series_name = series_folder.name
                
                # Count .dcm files in this series
                dcm_files = list(series_folder.glob("*.dcm"))
                slice_count = len(dcm_files)
                
                if slice_count > 0:  # Only record series with actual DICOM files
                    results.append({
                        "PatientID": patient_id,
                        "Study": study_name,
                        "Series": series_name,
                        "SliceCount": slice_count
                    })
    
    return results


def save_to_csv(results, output_file="ct_slices_per_series.csv"):
    """
    Save slice count results to CSV file.
    
    Args:
        results: List of dictionaries with slice data
        output_file: Output CSV filename
    """
    if not results:
        print("No results to save.")
        return
    
    fieldnames = ["PatientID", "Study", "Series", "SliceCount"]
    
    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    print(f"\n✓ Saved {len(results)} series to {output_file}")


def save_patient_summary_csv(patient_stats, output_file="ct_slices_per_patient_summary.csv"):
    """
    Save patient-level slice summary to CSV file.
    
    Args:
        patient_stats: Dictionary with patient statistics
        output_file: Output CSV filename
    """
    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["PatientID", "SeriesCount", "TotalSlices", "AvgSlicesPerSeries"])
        writer.writeheader()
        
        for patient_id in sorted(patient_stats.keys()):
            stats = patient_stats[patient_id]
            avg_slices = stats["total_slices"] / stats["series"] if stats["series"] > 0 else 0
            writer.writerow({
                "PatientID": patient_id,
                "SeriesCount": stats["series"],
                "TotalSlices": stats["total_slices"],
                "AvgSlicesPerSeries": f"{avg_slices:.1f}"
            })
    
    print(f"✓ Saved patient summary to {output_file}")


def print_statistics(results):
    """
    Print summary statistics about slices.
    """
    if not results:
        print("No results to analyze.")
        return
    
    slice_counts = [r["SliceCount"] for r in results]
    patient_ids = set(r["PatientID"] for r in results)
    
    print("\n" + "="*60)
    print("SLICE COUNT STATISTICS")
    print("="*60)
    print(f"Total CT series analyzed:        {len(results)}")
    print(f"Unique patients:                 {len(patient_ids)}")
    print(f"Total DICOM slices:              {sum(slice_counts)}")
    print(f"Average slices per series:       {sum(slice_counts) / len(slice_counts):.1f}")
    print(f"Min slices per series:           {min(slice_counts)}")
    print(f"Max slices per series:           {max(slice_counts)}")
    print("="*60)
    
    # Show top 10 most slices
    sorted_results = sorted(results, key=lambda x: x["SliceCount"], reverse=True)
    print("\nTop 10 Series with Most Slices:")
    print("-" * 60)
    for i, r in enumerate(sorted_results[:10], 1):
        print(f"{i:2}. {r['PatientID']} | {r['Series']:30} | {r['SliceCount']:3} slices")
    print("-" * 60)


def get_patient_summary(results):
    """
    Get aggregate statistics per patient.
    """
    patient_stats = defaultdict(lambda: {"series": 0, "total_slices": 0})
    
    for r in results:
        patient_id = r["PatientID"]
        patient_stats[patient_id]["series"] += 1
        patient_stats[patient_id]["total_slices"] += r["SliceCount"]
    
    return patient_stats


def main():
    print("Counting DICOM slices per CT imaging series...")
    print("This may take a minute or two...\n")
    
    # Count slices
    results = count_slices_per_series()
    
    # Save to CSV
    save_to_csv(results)
    
    # Patient summary
    patient_stats = get_patient_summary(results)
    save_patient_summary_csv(patient_stats)
    
    # Print statistics
    print_statistics(results)
    
    print("\nSample Patient Statistics (first 10):")
    print("-" * 60)
    for i, (patient_id, stats) in enumerate(sorted(patient_stats.items())[:10], 1):
        avg_slices = stats["total_slices"] / stats["series"] if stats["series"] > 0 else 0
        print(f"{i:2}. {patient_id}: {stats['series']} series, {stats['total_slices']} total slices (avg {avg_slices:.1f}/series)")
    print("-" * 60)


if __name__ == "__main__":
    main()
