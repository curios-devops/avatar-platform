"""
Local-file storage for development — no cloud credentials required.
Files are written to /tmp/avatar-dev/ and served at GET /dev-storage/{path}.
Only active when DEV_STORAGE=true in .env.
"""
import io
import os
import pathlib

DEV_ROOT = pathlib.Path("/tmp/avatar-dev")


class LocalStorageService:
    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        DEV_ROOT.mkdir(parents=True, exist_ok=True)
        self._base = base_url.rstrip("/")

    def upload_fileobj(self, file_obj: io.IOBase, object_key: str) -> str:
        dest = DEV_ROOT / object_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = file_obj.read()
        dest.write_bytes(data)
        return f"{self._base}/dev-storage/{object_key}"

    def upload_file(self, file_path: str, object_key: str) -> str:
        with open(file_path, "rb") as f:
            return self.upload_fileobj(f, object_key)

    def get_url(self, object_key: str, expiration: int = 3600) -> str:
        return f"{self._base}/dev-storage/{object_key}"

    def download_file(self, object_key: str, file_path: str) -> None:
        src = DEV_ROOT / object_key
        with open(file_path, "wb") as f:
            f.write(src.read_bytes())

    def delete_file(self, object_key: str) -> None:
        (DEV_ROOT / object_key).unlink(missing_ok=True)
