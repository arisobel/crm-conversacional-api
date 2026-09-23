"""Cliente HTTP isolado para o onboarding privado realizado pelo Gateway."""

from dataclasses import dataclass

import httpx

from crm_api.core.config import Settings


class GatewayOnboardingError(Exception):
    def __init__(self, detail: str, *, status_code: int = 503) -> None:
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class GatewayOnboarding:
    onboarding_id: str
    status: str
    launch_url: str | None = None
    failure_code: str | None = None
    display_phone_number: str | None = None
    gateway_line_reference: str | None = None


class GatewayWhatsappOnboardingClient:
    """Não retorna resposta bruta e nunca registra o token interno."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = (settings.whatsapp_gateway_base_url or "").rstrip("/")
        self._token = settings.whatsapp_gateway_internal_token
        self._timeout = settings.whatsapp_gateway_timeout_seconds

    def _ready(self) -> None:
        if not self._base_url or self._token is None:
            raise GatewayOnboardingError("whatsapp gateway onboarding is not configured")

    def _parse(self, payload: object, *, launch_required: bool = False) -> GatewayOnboarding:
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("onboarding_id"), str)
            or not isinstance(payload.get("status"), str)
        ):
            raise GatewayOnboardingError("gateway returned an invalid onboarding response")
        launch = payload.get("launch_url")
        if launch is not None and (not isinstance(launch, str) or not launch.startswith("/")):
            raise GatewayOnboardingError("gateway returned an invalid launch URL")
        if launch_required and not launch:
            raise GatewayOnboardingError("gateway did not provide a launch URL")
        return GatewayOnboarding(
            onboarding_id=payload["onboarding_id"],
            status=payload["status"],
            launch_url=launch,
            failure_code=payload.get("failure_code")
            if isinstance(payload.get("failure_code"), str)
            else None,
            display_phone_number=payload.get("display_phone_number")
            if isinstance(payload.get("display_phone_number"), str)
            else None,
            gateway_line_reference=payload.get("gateway_line_reference")
            if isinstance(payload.get("gateway_line_reference"), str)
            else None,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        idempotency_key: str | None = None,
        launch_required: bool = False,
    ) -> GatewayOnboarding:
        self._ready()
        headers = {"Authorization": f"Bearer {self._token.get_secret_value()}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
                response = await client.request(
                    method, f"{self._base_url}{path}", json=body, headers=headers
                )
        except httpx.TimeoutException as error:
            raise GatewayOnboardingError("gateway onboarding request timed out") from error
        except httpx.HTTPError as error:
            raise GatewayOnboardingError("gateway onboarding is unavailable") from error
        if response.status_code in {401, 403}:
            raise GatewayOnboardingError("gateway authentication failed")
        if response.status_code == 404:
            raise GatewayOnboardingError("gateway onboarding was not found", status_code=404)
        if response.status_code == 409:
            raise GatewayOnboardingError("gateway reported an onboarding conflict", status_code=409)
        if response.status_code >= 500:
            raise GatewayOnboardingError("gateway onboarding is unavailable")
        if response.status_code >= 400:
            raise GatewayOnboardingError("gateway rejected the onboarding request", status_code=422)
        try:
            return self._parse(response.json(), launch_required=launch_required)
        except ValueError as error:
            raise GatewayOnboardingError(
                "gateway returned an invalid onboarding response"
            ) from error

    async def create_onboarding(
        self, *, customer_reference: str, representative_reference: str, idempotency_key: str
    ) -> GatewayOnboarding:
        return await self._request(
            "POST",
            "/internal/meta/whatsapp/onboardings",
            body={
                "customer_reference": customer_reference,
                "representative_reference": representative_reference,
                "application_reference": "crm_textil",
                "flow_reference": "consulta_cliente",
            },
            idempotency_key=idempotency_key,
            launch_required=True,
        )

    async def get_onboarding(self, onboarding_id: str) -> GatewayOnboarding:
        return await self._request("GET", f"/internal/meta/whatsapp/onboardings/{onboarding_id}")

    async def resume_onboarding(
        self, onboarding_id: str, *, idempotency_key: str
    ) -> GatewayOnboarding:
        return await self._request(
            "POST",
            f"/internal/meta/whatsapp/onboardings/{onboarding_id}/resume",
            body={},
            idempotency_key=idempotency_key,
            launch_required=True,
        )
