"""File storage provider interface.

Swap LOCAL -> ONEDRIVE by setting STORAGE_BACKEND=onedrive once the Azure app
registration exists (see providers/graph_auth.py). Everything that calls a
provider only ever talks to this interface, so nothing else in the app changes
when the backend is switched — that's the whole point of the abstraction.
"""
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

LOCAL_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "local_storage"

_ILLEGAL_SEGMENT_CHARS = str.maketrans({c: "-" for c in '/\\:*?"<>|'})


def sanitize_segment(name: str) -> str:
    """Makes a single path segment (department/project name) safe as a folder
    name on both the local filesystem and OneDrive — real department names
    like "L1 TBU / PBU" contain "/", which both treat as a path separator.
    """
    return name.translate(_ILLEGAL_SEGMENT_CHARS).strip()


class StorageProvider(ABC):
    @abstractmethod
    def create_folder(self, path: str) -> str:
        """Create (or ensure) a folder tree exists. Returns a provider-specific folder ref."""

    @abstractmethod
    def upload_file(self, folder_ref: str, filename: str, content: bytes) -> str:
        """Upload a file into the folder. Returns a provider-specific file ref."""

    @abstractmethod
    def file_url(self, file_ref: str) -> str:
        """Best-effort link to view/download the file."""

    @abstractmethod
    def download_file(self, file_ref: str) -> bytes:
        """Read a file's raw bytes back, given a ref previously returned by upload_file."""

    def copy_file(self, file_ref: str, dest_folder_ref: str, filename: str) -> str:
        """Duplicate a file into another folder. Read+reupload works for any
        provider that implements download_file, so this needs no per-provider
        override (used for L0 -> L1 tender document copies).
        """
        return self.upload_file(dest_folder_ref, filename, self.download_file(file_ref))


class LocalStorageProvider(StorageProvider):
    """Pilot-phase stand-in: writes to a local folder inside this project.
    Lets the whole workflow (create project -> provision folders -> upload ->
    approve) be tested end to end today, with zero external accounts needed.
    """

    def create_folder(self, path: str) -> str:
        full = LOCAL_ROOT / path
        full.mkdir(parents=True, exist_ok=True)
        return str(path)

    def upload_file(self, folder_ref: str, filename: str, content: bytes) -> str:
        full_dir = LOCAL_ROOT / folder_ref
        full_dir.mkdir(parents=True, exist_ok=True)
        dest = full_dir / filename
        with open(dest, "wb") as f:
            f.write(content)
        return str(Path(folder_ref) / filename)

    def file_url(self, file_ref: str) -> str:
        return f"/local-files/{file_ref.replace(chr(92), '/')}"  # URL path needs "/" even on Windows, where file_ref carries native "\"

    def download_file(self, file_ref: str) -> bytes:
        return (LOCAL_ROOT / file_ref).read_bytes()


class OneDriveStorageProvider(StorageProvider):
    """Real implementation, backed by Microsoft Graph (/me/drive during the
    personal-OneDrive pilot; repoint at a SharePoint site drive later by
    changing the drive_id resolution below — same calls, same interface).
    Requires a working graph_auth.get_token() (delegated Files.ReadWrite).
    """

    def __init__(self):
        from . import graph_auth
        self.graph_auth = graph_auth
        self.base = "https://graph.microsoft.com/v1.0/me/drive"

    def _headers(self):
        import httpx  # noqa
        token = self.graph_auth.get_token()
        return {"Authorization": f"Bearer {token}"}

    def create_folder(self, path: str) -> str:
        import httpx
        parts = [p for p in path.split("/") if p]
        current_path = ""
        parent_ref = "root"
        for part in parts:
            current_path = f"{current_path}/{part}" if current_path else part
            url = f"{self.base}/root:/{current_path}"
            r = httpx.get(url, headers=self._headers())
            if r.status_code == 200:
                continue
            create_url = f"{self.base}/root:/{current_path.rsplit('/', 1)[0]}:/children" if "/" in current_path else f"{self.base}/root/children"
            body = {"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "replace"}
            httpx.post(create_url, headers={**self._headers(), "Content-Type": "application/json"}, json=body)
        return path

    def upload_file(self, folder_ref: str, filename: str, content: bytes) -> str:
        import httpx
        url = f"{self.base}/root:/{folder_ref}/{filename}:/content"
        r = httpx.put(url, headers=self._headers(), content=content)
        r.raise_for_status()
        item = r.json()
        return item.get("id", f"{folder_ref}/{filename}")

    def file_url(self, file_ref: str) -> str:
        import httpx
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_ref}"
        r = httpx.get(url, headers=self._headers())
        if r.status_code == 200:
            return r.json().get("webUrl", "")
        return ""

    def download_file(self, file_ref: str) -> bytes:
        import httpx
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_ref}/content"
        r = httpx.get(url, headers=self._headers())
        r.raise_for_status()
        return r.content


def get_storage_provider() -> StorageProvider:
    backend = os.environ.get("STORAGE_BACKEND", "local")
    if backend == "onedrive":
        return OneDriveStorageProvider()
    return LocalStorageProvider()
