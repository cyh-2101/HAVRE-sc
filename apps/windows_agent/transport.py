"""Device-authenticated HTTPS transport for the Windows ContextSource."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from companion.life_context import (
    ContextCollectionPermit,
    ContextCollectionPermitRequest,
    ContextIngestResult,
    ContextObservationDraft,
    ContextSourceHealthDraft,
    ContextSourceHealthV2,
    sign_collection_permit_request,
)


class ContextTransportError(RuntimeError):
    pass


class ContextTransportUnavailable(ContextTransportError):
    pass


class ContextTransportRejected(ContextTransportError):
    pass


class WindowsAgentTransport:
    def __init__(
        self, *, base_url: str, owner_id: UUID, source_instance_id: UUID,
        device_binding_id: str, signing_secret: bytes,
        client: httpx.Client | None = None,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("Windows context transport requires HTTPS")
        if len(signing_secret) < 32:
            raise ValueError("device signing secret must contain at least 32 bytes")
        self.base_url = normalized
        self.owner_id = owner_id
        self.source_instance_id = source_instance_id
        self.device_binding_id = device_binding_id
        self.signing_secret = signing_secret
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(15.0), verify=True, follow_redirects=False
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def request_permit(self) -> ContextCollectionPermit:
        request = sign_collection_permit_request(
            ContextCollectionPermitRequest(
                owner_id=self.owner_id,
                source_instance_id=self.source_instance_id,
                device_binding_id=self.device_binding_id,
                requested_at=datetime.now(UTC),
                nonce=uuid4().hex,
            ),
            secret=self.signing_secret,
        )
        return ContextCollectionPermit.model_validate(
            self._post("/v1/context/collection-permit", request.model_dump(mode="json"))
        )

    def submit_observation(self, draft: ContextObservationDraft) -> ContextIngestResult:
        return ContextIngestResult.model_validate(
            self._post("/v1/context/observations", draft.model_dump(mode="json"))
        )

    def submit_health(self, draft: ContextSourceHealthDraft) -> ContextSourceHealthV2:
        return ContextSourceHealthV2.model_validate(
            self._post("/v1/context/health", draft.model_dump(mode="json"))
        )

    def _post(self, path: str, payload: dict[str, object]) -> object:
        try:
            response = self.client.post(f"{self.base_url}{path}", json=payload)
        except httpx.HTTPError as error:
            raise ContextTransportUnavailable("owner Core is unavailable") from error
        if response.is_redirect:
            raise ContextTransportError("context transport refused an HTTPS redirect")
        if response.status_code != 200:
            error_type = (
                ContextTransportRejected
                if 400 <= response.status_code < 500
                else ContextTransportUnavailable
            )
            raise error_type(
                f"owner Core rejected context request with status {response.status_code}"
            )
        return response.json()
