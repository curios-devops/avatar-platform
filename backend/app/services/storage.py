import io
import logging
from typing import Union

import boto3
from botocore.client import Config

from ..config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """
    Cloudflare R2 storage via the S3-compatible API (boto3).

    R2 notes:
    - Endpoint: https://<CLOUDFLARE_ACCOUNT_ID>.r2.cloudflarestorage.com
    - Region is always "auto"
    - R2 does not support per-object ACLs; enable bucket-level "Public Access"
      in the R2 dashboard and set R2_PUBLIC_BASE_URL to get stable public URLs.
    """

    def __init__(self) -> None:
        endpoint = f"https://{settings.CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
        logger.info("Storage: Cloudflare R2 — %s / %s", endpoint, settings.R2_BUCKET_NAME)

        self._bucket = settings.R2_BUCKET_NAME
        self._public_base = (settings.public_base_url or "").rstrip("/")
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            try:
                self._client.create_bucket(Bucket=self._bucket)
                logger.info("Storage: created R2 bucket %s", self._bucket)
            except Exception as exc:
                logger.warning("Storage: could not verify bucket %s — %s", self._bucket, exc)

    # ── Core upload ops ───────────────────────────────────────────────────────

    def upload_file(self, file_path: str, object_key: str) -> str:
        self._client.upload_file(file_path, self._bucket, object_key)
        return self.get_url(object_key)

    def upload_fileobj(self, file_obj: io.IOBase, object_key: str) -> str:
        self._client.upload_fileobj(file_obj, self._bucket, object_key)
        return self.get_url(object_key)

    def download_file(self, object_key: str, file_path: str) -> None:
        self._client.download_file(self._bucket, object_key, file_path)

    def delete_file(self, object_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=object_key)

    # ── URL generation ────────────────────────────────────────────────────────

    def get_url(self, object_key: str, expiration: int = 3600) -> str:
        if self._public_base:
            return f"{self._public_base}/{object_key}"
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": object_key},
            ExpiresIn=expiration,
        )


def _build_storage_service():
    if settings.DEV_STORAGE:
        from .local_storage import LocalStorageService
        logger.info("Storage: LOCAL (/tmp/avatar-dev/) — dev mode only")
        return LocalStorageService(base_url="http://localhost:8000")
    return StorageService()


storage_service = _build_storage_service()
