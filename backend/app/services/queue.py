import redis
import json
from typing import Dict, Optional
from datetime import datetime
from ..config import settings


class QueueService:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True
        )

    def submit_job(self, job_type: str, job_data: Dict) -> str:
        """Submit a new job to the queue"""
        job_id = f"{job_type}_{datetime.utcnow().timestamp()}"

        job = {
            "id": job_id,
            "type": job_type,
            "status": "pending",
            "progress": 0.0,
            "data": job_data,
            "created_at": datetime.utcnow().isoformat()
        }

        # Store job in Redis
        self.redis_client.hset(f"job:{job_id}", mapping={
            "data": json.dumps(job)
        })

        # Add to queue
        self.redis_client.lpush(f"queue:{job_type}", job_id)

        return job_id

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get current status of a job"""
        job_data = self.redis_client.hget(f"job:{job_id}", "data")
        if job_data:
            return json.loads(job_data)
        return None

    def update_job_status(self, job_id: str, status: str, progress: float = 0.0,
                         result: Optional[Dict] = None, error: Optional[str] = None):
        """Update job status"""
        job = self.get_job_status(job_id)
        if job:
            job["status"] = status
            job["progress"] = progress
            if result:
                # Merge into existing result so accumulated data (e.g. multiview_images)
                # persists across subsequent stage updates.
                if job.get("result"):
                    job["result"].update(result)
                else:
                    job["result"] = result
            if error:
                job["error"] = error

            self.redis_client.hset(f"job:{job_id}", "data", json.dumps(job))

    def get_next_job(self, job_type: str) -> Optional[str]:
        """Get next job from queue (blocking)"""
        result = self.redis_client.brpop(f"queue:{job_type}", timeout=1)
        if result:
            return result[1]
        return None


queue_service = QueueService()
