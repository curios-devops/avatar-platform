from .schemas import GaussianSet, BindingTable

FLAME_TRIANGLE_COUNT = 9976  # FLAME 2023 topology — pin this; downstream animation breaks on drift
UNMODELED = ["tongue", "mouth_interior_detail"]


def rig(gaussian_set: GaussianSet) -> BindingTable:
    """
    Validate and assemble the Gaussian→FLAME binding table.
    Verifies every Gaussian has a valid triangle index and barycentric coords.
    Raises ValueError if any Gaussian is unbound or out-of-range.
    """
    for i, g in enumerate(gaussian_set.gaussians):
        if g.triangle_idx < 0 or g.triangle_idx >= FLAME_TRIANGLE_COUNT:
            raise ValueError(
                f"Gaussian {i}: triangle_idx {g.triangle_idx} out of range "
                f"[0, {FLAME_TRIANGLE_COUNT})"
            )
        bary_sum = sum(g.barycentric)
        if abs(bary_sum - 1.0) > 1e-4:
            raise ValueError(
                f"Gaussian {i}: barycentric coords sum to {bary_sum:.6f}, expected 1.0"
            )

    return BindingTable(
        gaussian_count=len(gaussian_set.gaussians),
        flame_triangle_count=FLAME_TRIANGLE_COUNT,
        unmodeled=UNMODELED,
        is_complete=True,
    )
