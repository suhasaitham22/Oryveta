"""Private artifact publication for one Evolve attempt.

An artifact becomes visible to a project's authorized users in two steps that
must happen in this order: the live worker uploads the bytes to the private
`evolve-artifacts` bucket at the canonical path `<run_id>/<kind>/<sha256>`, and
only then registers the record that makes them readable. A staged object with no
registration is not readable under the bucket's policies. The bucket has no
public URL; readers fetch registered bytes through their own
authenticated session.

Objects are insert-only. After an interrupted upload, the worker can register
the existing digest path, then independently confirm its bytes before using it.
Neither a retry nor a compromised client can overwrite a registered object.

This module reuses the worker's existing authenticated session rather than
holding a credential of its own. The bytes it uploads are already sanitized by
the caller; nothing here inspects or rewrites them.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any

import httpx

from .coding_contract import CodingError
from .evolve_contract import ARTIFACT_KINDS, ARTIFACT_LIMITS
from .factory_runtime import ControlPlaneUnavailable, FactoryRuntimeClient, FactoryRuntimeError

BUCKET = "evolve-artifacts"
UPLOAD_TIMEOUT_SECONDS = 120.0


class EvolveArtifactStore:
    """Uploads and registers one attempt's artifacts with the worker's session."""

    def __init__(self, client: FactoryRuntimeClient, *, bucket: str = BUCKET,
                 timeout: float = UPLOAD_TIMEOUT_SECONDS,
                 transport: httpx.BaseTransport | None = None):
        self.client = client
        self.bucket = bucket
        self._http = httpx.Client(
            base_url=client.credentials.supabase_url, timeout=timeout, trust_env=False,
            follow_redirects=False, transport=transport,
            headers={"apikey": client.credentials.publishable_key, "Accept": "application/json"})

    def __enter__(self) -> EvolveArtifactStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def storage_path(self, run_id: str, kind: str, digest: str) -> str:
        return f"{run_id}/{kind}/{digest}"

    def _upload(self, path: str, payload: bytes) -> bool:
        """Insert an immutable object; return whether a prior upload exists."""
        target = f"/storage/v1/object/{self.bucket}/{path}"
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {self.client.access_token(bool(attempt))}",
                       "Content-Type": "application/octet-stream", "x-upsert": "false"}
            try:
                response = self._http.post(target, content=payload, headers=headers)
            except (httpx.HTTPError, httpx.StreamError) as exception:
                raise ControlPlaneUnavailable(
                    "the artifact store could not be reached for this upload") from exception
            if response.status_code in {401, 403} and not attempt:
                continue
            if response.is_success:
                return False
            if response.status_code == 409:
                return True
            # Only the status is retained: a storage error body can echo the
            # request, and no upstream text belongs in a worker's output.
            raise FactoryRuntimeError(
                f"artifact upload was refused with HTTP {response.status_code}")
        raise FactoryRuntimeError("artifact upload was refused after a session refresh")

    def _verify_existing(self, path: str, digest: str, size: int) -> None:
        """Verify an interrupted upload after registration makes it readable."""
        observed = sha256()
        length = 0
        try:
            with self._http.stream(
                "GET", f"/storage/v1/object/authenticated/{self.bucket}/{path}",
                headers={"Authorization": f"Bearer {self.client.access_token()}"},
            ) as response:
                if not response.is_success:
                    raise FactoryRuntimeError("existing artifact could not be verified")
                for chunk in response.iter_bytes():
                    length += len(chunk)
                    if length > size:
                        raise FactoryRuntimeError("existing artifact exceeds its declared size")
                    observed.update(chunk)
        except httpx.HTTPError as exception:
            raise ControlPlaneUnavailable("existing artifact could not be read") from exception
        if length != size or observed.hexdigest() != digest:
            raise FactoryRuntimeError("existing artifact does not match its recorded digest")

    def publish(self, run_id: str, lease_token: str, kind: str, payload: bytes) -> dict[str, Any]:
        """Upload then register one artifact, returning the registered row.

        The digest is taken from the bytes being uploaded, so a caller cannot
        register one artifact and store another, and the registered path is
        compared against the canonical path this worker wrote.
        """
        if kind not in ARTIFACT_KINDS:
            raise CodingError("invalid_artifact", "unsupported Evolve artifact kind")
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            raise CodingError("invalid_artifact", f"the {kind} artifact has no bytes")
        if len(payload) > ARTIFACT_LIMITS[kind]:
            raise CodingError("artifact_limit", f"the {kind} artifact exceeds its size limit")
        payload = bytes(payload)
        digest = sha256(payload).hexdigest()
        path = self.storage_path(run_id, kind, digest)
        existed = self._upload(path, payload)
        row = self.client.rpc_row("register_evolve_artifact", {
            "p_run_id": run_id, "p_lease_token": lease_token, "p_kind": kind,
            "p_sha256": digest, "p_bytes": len(payload),
        })
        if not isinstance(row, dict):
            raise FactoryRuntimeError("artifact registration returned no row")
        if row.get("sha256") != digest or row.get("bytes") != len(payload):
            raise FactoryRuntimeError("artifact registration does not match the uploaded bytes")
        if row.get("storage_path") != path:
            raise FactoryRuntimeError("artifact registration names another storage path")
        if existed:
            self._verify_existing(path, digest, len(payload))
        return row
