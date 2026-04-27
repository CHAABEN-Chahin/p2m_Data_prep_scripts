"""
Utility functions for 3D nodule patch extraction and preprocessing.

Coordinate system note
----------------------
SimpleITK reads NIfTI files produced by this pipeline and uses (x, y, z) index order.
nibabel reads the same files with the same (i, j, k) = (x, y, z) order.
pylidc cbbox slices index into an array whose shape matches the nibabel array shape.
Therefore pylidc centroid (ci, cj, ck) == sitk index (ci, cj, ck).

sitk.GetArrayFromImage() transposes to numpy (z, y, x) convention.
After mapping a centroid through physical coordinates to the resampled image, the
returned sitk index (rx, ry, rz) must be accessed in numpy as (rz, ry, rx).
"""

from typing import Tuple
import numpy as np
import SimpleITK as sitk


def resample_volume_isotropic(
    image: sitk.Image,
    target_spacing: float = 1.0,
    interpolator=sitk.sitkLinear,
    default_pixel_value: float = -1000.0,
) -> sitk.Image:
    """Resample a SimpleITK CT image to isotropic voxel spacing (default 1 mm)."""
    orig_spacing = image.GetSpacing()   # (sx, sy, sz) in mm
    orig_size = image.GetSize()         # (nx, ny, nz) in voxels

    new_size = [
        int(round(orig_size[i] * orig_spacing[i] / target_spacing))
        for i in range(3)
    ]

    resampler = sitk.ResampleImageFilter()
    resampler.SetOutputSpacing((target_spacing,) * 3)
    resampler.SetSize(new_size)
    resampler.SetOutputDirection(image.GetDirection())
    resampler.SetOutputOrigin(image.GetOrigin())
    resampler.SetTransform(sitk.Transform())
    resampler.SetDefaultPixelValue(default_pixel_value)
    resampler.SetInterpolator(interpolator)

    return resampler.Execute(image)


def centroid_to_resampled_index(
    centroid_ijk: Tuple[float, float, float],
    original_image: sitk.Image,
    resampled_image: sitk.Image,
) -> Tuple[int, int, int]:
    """
    Map a centroid from original sitk/nibabel index space to resampled sitk index space.

    Uses physical coordinates as the bridge so spacing changes are handled correctly.
    Returns sitk index (cx, cy, cz) — note: numpy from sitk is (cz, cy, cx).
    """
    world_pt = original_image.TransformContinuousIndexToPhysicalPoint(
        (float(centroid_ijk[0]), float(centroid_ijk[1]), float(centroid_ijk[2]))
    )
    return resampled_image.TransformPhysicalPointToIndex(world_pt)


def extract_patch_3d(
    vol_zyx: np.ndarray,
    centroid_zyx: Tuple[int, int, int],
    patch_size: int = 48,
    pad_value: float = -1000.0,
) -> np.ndarray:
    """
    Extract a cubic patch centred on centroid from a volume in (z, y, x) numpy convention.

    Pads with pad_value when the centroid is near a volume border.
    Returns float32 array of shape (patch_size, patch_size, patch_size).
    """
    cz, cy, cx = (int(round(v)) for v in centroid_zyx)
    half = patch_size // 2
    Nz, Ny, Nx = vol_zyx.shape

    patch = np.full(
        (patch_size, patch_size, patch_size),
        fill_value=pad_value,
        dtype=np.float32,
    )

    # Source window clamped to volume bounds
    sz0 = max(0, cz - half);  sz1 = min(Nz, cz + half)
    sy0 = max(0, cy - half);  sy1 = min(Ny, cy + half)
    sx0 = max(0, cx - half);  sx1 = min(Nx, cx + half)

    # Destination window inside the patch (offset by how much we clamped)
    dz0 = sz0 - (cz - half);  dz1 = dz0 + (sz1 - sz0)
    dy0 = sy0 - (cy - half);  dy1 = dy0 + (sy1 - sy0)
    dx0 = sx0 - (cx - half);  dx1 = dx0 + (sx1 - sx0)

    patch[dz0:dz1, dy0:dy1, dx0:dx1] = (
        vol_zyx[sz0:sz1, sy0:sy1, sx0:sx1].astype(np.float32)
    )
    return patch


def normalize_patch(
    patch: np.ndarray,
    hu_min: float = -1000.0,
    hu_max: float = 400.0,
) -> np.ndarray:
    """Clip HU values and linearly normalise to [0, 1] float32."""
    clipped = np.clip(patch.astype(np.float32), hu_min, hu_max)
    return (clipped - hu_min) / (hu_max - hu_min)
