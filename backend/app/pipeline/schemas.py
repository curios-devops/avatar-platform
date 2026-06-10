from pydantic import BaseModel, Field, model_validator
from typing import Optional


class IngestResult(BaseModel):
    photo_url: str
    width: int
    height: int
    face_count: int
    face_bbox: list[float]  # [x0, y0, x1, y1] normalized 0–1


class FlameParams(BaseModel):
    shape: list[float] = Field(..., description="300-dim shape coefficients")
    expression: list[float] = Field(..., description="100-dim expression (neutral=zeros)")
    pose: list[float] = Field(..., description="6-dim pose: jaw, neck, global rotation")
    tex: list[float] = Field(..., description="50-dim texture coefficients")


class GaussianSplat(BaseModel):
    position: list[float]    # [x, y, z] in meters
    opacity: float
    scale: list[float]       # [sx, sy, sz]
    rotation: list[float]    # quaternion [w, x, y, z]
    sh_dc: list[float]       # 3 DC spherical harmonics (RGB)
    triangle_idx: int        # FLAME triangle index
    barycentric: list[float] # [u, v, w] summing to 1.0


class GaussianSet(BaseModel):
    gaussians: list[GaussianSplat]

    @model_validator(mode="after")
    def validate_bindings(self) -> "GaussianSet":
        for i, g in enumerate(self.gaussians):
            s = sum(g.barycentric)
            if abs(s - 1.0) > 1e-4:
                raise ValueError(
                    f"Gaussian {i} barycentric coords sum to {s:.6f}, expected 1.0"
                )
        return self


class BindingTable(BaseModel):
    gaussian_count: int
    flame_triangle_count: int
    unmodeled: list[str]
    is_complete: bool


class MICAResult(BaseModel):
    """Output from MICA identity reconstruction (Phase 2)."""
    shape: list[float]          # 300-dim stable identity coefficients


class EMOCAResult(BaseModel):
    """Output from EMOCA detailed face reconstruction (Phase 2)."""
    flame_params: FlameParams           # shape + expression + pose + tex
    albedo_jpeg: bytes                  # 1024×1024 RGB JPEG albedo texture
    displacement_npy: Optional[bytes] = None  # 512×512 float32 NPY displacement (optional)
    expression_basis: Optional[list[list[float]]] = None  # (100, 5023×3) PCA basis


class AvatarBundleFlame(BaseModel):
    params: str              # URL to flame_params.json
    topology_version: str = "FLAME_2023"


class AvatarBundle(BaseModel):
    version: str = "1.0"
    coordinate_system: str = "y_up_right_handed"
    scale_units: str = "meters"
    gaussians: str               # URL to gaussians.ply
    flame: AvatarBundleFlame
    binding: str                 # URL to gaussian_flame_binding.npz
    eyes: str                    # URL to eyes.glb  (Phase 3)
    teeth: str                   # URL to teeth.glb (Phase 3)
    body: str                    # URL to body.glb  (Phase 3)
    expression_basis: str = "ARKit_52"
    unmodeled: list[str]         # intentionally unmodeled regions
    preview: str                 # URL to neutral_front.png

    @model_validator(mode="after")
    def validate_required_urls(self) -> "AvatarBundle":
        if not self.gaussians:
            raise ValueError("Missing gaussians URL")
        if not self.binding:
            raise ValueError("Missing binding table URL — all Gaussians must be bound")
        if not self.flame or not self.flame.params:
            raise ValueError("Missing FLAME params URL")
        return self
