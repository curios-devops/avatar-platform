import os
import subprocess
from pathlib import Path
import requests
from .colmap_runner import COLMAPRunner
from .gsplat_trainer import GsplatTrainer
import tempfile
import shutil


def extract_frames_from_video(video_path: str, output_dir: str, fps: int = 30):
    """Extract frames from video using ffmpeg"""
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vf", f"fps={fps}",
        f"{output_dir}/frame_%04d.png"
    ]
    subprocess.run(cmd, check=True)


def download_file(url: str, output_path: str):
    """Download file from URL"""
    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def reconstruct_avatar(video_url: str, mode: str = "head", job_id: str = None) -> dict:
    """
    Main reconstruction pipeline

    Pipeline:
    1. Download video
    2. Extract frames
    3. Run COLMAP (pose estimation)
    4. Run SplattingAvatar preprocessing
    5. Train gsplat model
    6. Export gaussian .ply

    Args:
        video_url: URL to video file
        mode: 'head' or 'full_body'
        job_id: Job ID for progress tracking

    Returns:
        Dict with paths to outputs
    """
    # Create temporary workspace
    workspace = Path(tempfile.mkdtemp(prefix="avatar_reconstruction_"))
    print(f"Workspace: {workspace}")

    try:
        # Step 1: Download video
        print("Downloading video...")
        video_path = workspace / "input_video.mp4"
        download_file(video_url, str(video_path))

        # Step 2: Extract frames
        print("Extracting frames...")
        images_dir = workspace / "images"
        images_dir.mkdir(exist_ok=True)
        extract_frames_from_video(str(video_path), str(images_dir))

        # Step 3: Run COLMAP
        print("Running COLMAP pose estimation...")
        colmap_runner = COLMAPRunner(str(workspace))
        sparse_model_path = colmap_runner.run_full_pipeline()

        # Step 4: SplattingAvatar preprocessing
        # TODO: Implement SplattingAvatar specific preprocessing
        # This would include:
        # - Head segmentation (if mode == 'head')
        # - FLAME fitting (parametric head model)
        # - Create canonical space mapping
        print("Running SplattingAvatar preprocessing...")

        # Step 5: Train gsplat model
        print("Training Gaussian Splatting model...")
        output_dir = workspace / "output"
        trainer = GsplatTrainer(str(workspace), str(output_dir))
        result = trainer.train(num_iterations=30000)

        # Step 6: Upload outputs to S3
        # In production, upload to S3 and return URLs
        print("Reconstruction complete!")

        return {
            "avatar_id": f"avatar_{job_id}",
            "gaussian_ply": result["gaussian_ply"],
            "metadata": result["metadata"],
            "workspace": str(workspace)
        }

    except Exception as e:
        print(f"Error during reconstruction: {e}")
        # Clean up workspace on error
        shutil.rmtree(workspace, ignore_errors=True)
        raise
