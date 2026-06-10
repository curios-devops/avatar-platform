import runpod
from reconstruction.splatting_avatar import reconstruct_avatar
from animation.gaussian_speech import animate_avatar
import json


def handler(event):
    """
    Main RunPod handler
    Routes jobs to appropriate pipeline
    """
    job_input = event["input"]
    job_type = job_input.get("job_type")
    job_id = job_input.get("job_id")

    try:
        if job_type == "reconstruction":
            # RECONSTRUCTION MODE
            # Input: video
            # Output: gaussian splats
            result = reconstruct_avatar(
                video_url=job_input["video_url"],
                mode=job_input.get("mode", "head"),
                job_id=job_id
            )

            return {
                "status": "success",
                "output": result
            }

        elif job_type == "animation":
            # ANIMATION MODE
            # Input: audio + avatar
            # Output: deformation stream
            result = animate_avatar(
                avatar_id=job_input["avatar_id"],
                audio_url=job_input["audio_url"],
                job_id=job_id
            )

            return {
                "status": "success",
                "output": result
            }

        else:
            return {
                "status": "error",
                "error": f"Unknown job type: {job_type}"
            }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


# Start RunPod handler
runpod.serverless.start({"handler": handler})
