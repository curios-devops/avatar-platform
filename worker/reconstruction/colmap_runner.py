import subprocess
import os
from pathlib import Path


class COLMAPRunner:
    """
    Runs COLMAP for camera pose estimation
    """

    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.images_dir = self.workspace_dir / "images"
        self.database_path = self.workspace_dir / "database.db"
        self.sparse_dir = self.workspace_dir / "sparse"
        self.sparse_dir.mkdir(exist_ok=True)

    def run_feature_extraction(self):
        """Extract SIFT features from images"""
        cmd = [
            "colmap", "feature_extractor",
            "--database_path", str(self.database_path),
            "--image_path", str(self.images_dir),
            "--ImageReader.single_camera", "1",
            "--ImageReader.camera_model", "OPENCV",
            "--SiftExtraction.use_gpu", "1"
        ]
        subprocess.run(cmd, check=True)

    def run_feature_matching(self):
        """Match features between images"""
        cmd = [
            "colmap", "exhaustive_matcher",
            "--database_path", str(self.database_path),
            "--SiftMatching.use_gpu", "1"
        ]
        subprocess.run(cmd, check=True)

    def run_mapper(self):
        """Run incremental mapping"""
        cmd = [
            "colmap", "mapper",
            "--database_path", str(self.database_path),
            "--image_path", str(self.images_dir),
            "--output_path", str(self.sparse_dir)
        ]
        subprocess.run(cmd, check=True)

    def run_full_pipeline(self):
        """Run complete COLMAP pipeline"""
        print("Running COLMAP feature extraction...")
        self.run_feature_extraction()

        print("Running COLMAP feature matching...")
        self.run_feature_matching()

        print("Running COLMAP mapper...")
        self.run_mapper()

        print("COLMAP pipeline complete!")
        return str(self.sparse_dir / "0")
