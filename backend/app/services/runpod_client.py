import requests
from typing import Dict, Optional
from ..config import settings


class RunPodClient:
    def __init__(self):
        self.api_key = settings.RUNPOD_API_KEY
        self.endpoint_id = settings.RUNPOD_ENDPOINT_ID
        self.base_url = f"https://api.runpod.ai/v2/{self.endpoint_id}"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def submit_job(self, job_type: str, input_data: Dict) -> str:
        """Submit job to RunPod"""
        payload = {
            "input": {
                "job_type": job_type,
                **input_data
            }
        }

        response = requests.post(
            f"{self.base_url}/run",
            json=payload,
            headers=self.headers
        )
        response.raise_for_status()

        result = response.json()
        return result["id"]

    def get_job_status(self, job_id: str) -> Dict:
        """Poll job status from RunPod"""
        response = requests.get(
            f"{self.base_url}/status/{job_id}",
            headers=self.headers
        )
        response.raise_for_status()

        return response.json()

    def cancel_job(self, job_id: str):
        """Cancel running job"""
        response = requests.post(
            f"{self.base_url}/cancel/{job_id}",
            headers=self.headers
        )
        response.raise_for_status()


runpod_client = RunPodClient()
