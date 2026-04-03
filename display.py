import pydicom
import matplotlib.pyplot as plt
from pathlib import Path

# Load file
dcm_path = Path(
	"D:/DATA/manifest-1600709154662/LIDC-IDRI/LIDC-IDRI-0896/01-01-2000-NA-NA-74946/3000057.000000-NA-28864/1-002.dcm"
)
ds = pydicom.dcmread(dcm_path)

# Access pixel data
image = ds.pixel_array
print(f"Loaded DICOM. Shape={image.shape}, dtype={image.dtype}")

# Show image
plt.imshow(image, cmap="gray")
plt.title("CT Slice")
plt.axis("off")
plt.tight_layout()
output_path = Path(__file__).with_name("ct_slice_preview.png")
plt.savefig(output_path, dpi=150)
print(f"Saved preview to {output_path}")
plt.show(block=True)