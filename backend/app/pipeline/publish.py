import io
from typing import Callable

from .schemas import AvatarBundle, AvatarBundleFlame


def publish(
    job_id: str,
    artifacts: dict[str, bytes],
    upload_fn: Callable[[io.BytesIO, str], str],
) -> AvatarBundle:
    """
    Upload all AvatarBundle artifacts to storage.
    Returns AvatarBundle manifest with final storage URLs.
    upload_fn(file_obj, object_key) -> url  (matches StorageService.upload_fileobj signature)
    """
    urls: dict[str, str] = {}
    for filename, data in artifacts.items():
        key = f"avatars/{job_id}/{filename}"
        urls[filename] = upload_fn(io.BytesIO(data), key)

    return AvatarBundle(
        version="1.0",
        coordinate_system="y_up_right_handed",
        scale_units="meters",
        gaussians=urls["gaussians.ply"],
        flame=AvatarBundleFlame(
            params=urls["flame_params.json"],
            topology_version="FLAME_2023",
        ),
        binding=urls["gaussian_flame_binding.npz"],
        eyes=urls["eyes.glb"],
        teeth=urls["teeth.glb"],
        body=urls["body.glb"],
        expression_basis="ARKit_52",
        unmodeled=["mouth_interior_detail"],
        preview=urls["neutral_front.png"],
    )
