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


@dataclass(frozen=True)
class GatewaySimulationResult:
    status: str
    reply: str
    source: str
    capability_id: str | None = None
    capability_title: str | None = None
    action: str | None = None
    requires_confirmation: bool = False
    slots: dict[str, str] | None = None


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
        """Retoma o trabalho server-side; o Gateway pode não pedir nova interação Meta."""
        return await self._request(
            "POST",
            f"/internal/meta/whatsapp/onboardings/{onboarding_id}/resume",
            body={},
            idempotency_key=idempotency_key,
        )

    async def resume_handoff(
        self, *, gateway_line_reference: str, contact_phone_e164: str, idempotency_key: str
    ) -> str:
        """Entrega ao Gateway um comando explícito do portal para retomar o assistente."""
        self._ready()
        headers = {
            "Authorization": f"Bearer {self._token.get_secret_value()}",
            "Idempotency-Key": idempotency_key,
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
                response = await client.post(
                    f"{self._base_url}/internal/whatsapp/handoffs/resume",
                    json={
                        "gateway_line_reference": gateway_line_reference,
                        "contact_phone_e164": contact_phone_e164,
                    },
                    headers=headers,
                )
        except httpx.TimeoutException as error:
            raise GatewayOnboardingError("gateway handoff request timed out") from error
        except httpx.HTTPError as error:
            raise GatewayOnboardingError("gateway handoff is unavailable") from error
        if response.status_code in {401, 403}:
            raise GatewayOnboardingError("gateway authentication failed")
        if response.status_code >= 500:
            raise GatewayOnboardingError("gateway handoff is unavailable")
        if response.status_code >= 400:
            raise GatewayOnboardingError("gateway rejected the handoff request", status_code=422)
        try:
            status = response.json().get("status")
        except ValueError as error:
            raise GatewayOnboardingError("gateway returned an invalid handoff response") from error
        if status not in {"RESUMED", "ASSISTANT_ACTIVE"}:
            raise GatewayOnboardingError("gateway returned an invalid handoff response")
        return status

    async def handoff_status(
        self, *, gateway_line_reference: str, contact_phone_e164: str
    ) -> str:
        self._ready()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
                response = await client.post(
                    f"{self._base_url}/internal/whatsapp/handoffs/status",
                    json={
                        "gateway_line_reference": gateway_line_reference,
                        "contact_phone_e164": contact_phone_e164,
                    },
                    headers={"Authorization": f"Bearer {self._token.get_secret_value()}"},
                )
        except httpx.HTTPError as error:
            raise GatewayOnboardingError("gateway handoff is unavailable") from error
        if response.status_code >= 400:
            raise GatewayOnboardingError("gateway rejected the handoff request", status_code=422)
        try:
            status = response.json().get("status")
        except ValueError as error:
            raise GatewayOnboardingError("gateway returned an invalid handoff response") from error
        if status not in {"HUMAN_HANDOFF", "ASSISTANT_ACTIVE"}:
            raise GatewayOnboardingError("gateway returned an invalid handoff response")
        return status

    async def status_overview(self) -> dict:
        """Lê somente o resumo operacional sanitizado do Gateway."""
        self._ready()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(min(self._timeout, 3.0))) as client:
                response = await client.get(
                    f"{self._base_url}/internal/status/overview",
                    headers={"Authorization": f"Bearer {self._token.get_secret_value()}"},
                )
        except httpx.TimeoutException as error:
            raise GatewayOnboardingError("gateway status request timed out") from error
        except httpx.HTTPError as error:
            raise GatewayOnboardingError("gateway status is unavailable") from error
        if response.status_code in {401, 403}:
            raise GatewayOnboardingError("gateway authentication failed")
        if response.status_code >= 400:
            raise GatewayOnboardingError("gateway status is unavailable")
        try:
            payload = response.json()
        except ValueError as error:
            raise GatewayOnboardingError("gateway returned an invalid status response") from error
        if (
            not isinstance(payload, dict)
            or payload.get("servico") != "whatsapp-webhook-caprover"
            or not isinstance(payload.get("linhas"), list)
        ):
            raise GatewayOnboardingError("gateway returned an invalid status response")
        raw_features = payload.get("recursos")
        raw_features = raw_features if isinstance(raw_features, dict) else {}
        raw_audio_limit = raw_features.get("limite_audio_segundos")
        audio_limit = raw_audio_limit if type(raw_audio_limit) in {int, float} else 0
        return {
            "service": payload["servico"],
            "version": str(payload.get("versao") or "unknown")[:80],
            "generated_at": payload.get("gerado_em"),
            "applications": int(payload.get("aplicativos") or 0),
            "flows": int(payload.get("fluxos") or 0),
            "active_contacts_7d": int(payload.get("contatos_ativos_7d") or 0),
            "active_conversations": int(payload.get("conversas_ativas") or 0),
            "features": {
                "voice_transcription": raw_features.get("transcricao_audio") is True,
                "natural_replies": raw_features.get("respostas_naturais") is True,
                "automatic_handoff": raw_features.get("transbordo_automatico") is True,
                "max_audio_seconds": max(0, min(int(audio_limit), 600)),
            },
            "lines": [
                {
                    "label": str(item.get("rotulo") or "Linha WhatsApp")[:120],
                    "status": str(item.get("status") or "UNKNOWN")[:32],
                    "flow": str(item.get("fluxo") or "")[:160],
                }
                for item in payload["linhas"][:50]
                if isinstance(item, dict)
            ],
        }

    async def simulate_message(
        self,
        *,
        actor_role: str,
        text: str,
        capabilities: list[dict],
        history: list[dict[str, str]],
    ) -> GatewaySimulationResult:
        """Interpreta no Gateway sem enviar mensagem nem executar uma ação."""
        self._ready()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
                response = await client.post(
                    f"{self._base_url}/internal/simulator/interpret",
                    json={
                        "actor_role": actor_role,
                        "text": text,
                        "capabilities": capabilities,
                        "history": history,
                    },
                    headers={"Authorization": f"Bearer {self._token.get_secret_value()}"},
                )
        except httpx.TimeoutException as error:
            raise GatewayOnboardingError("gateway simulator request timed out") from error
        except httpx.HTTPError as error:
            raise GatewayOnboardingError("gateway simulator is unavailable") from error
        if response.status_code in {401, 403}:
            raise GatewayOnboardingError("gateway authentication failed")
        if response.status_code >= 500:
            raise GatewayOnboardingError("gateway simulator is unavailable")
        if response.status_code >= 400:
            raise GatewayOnboardingError("gateway rejected the simulation", status_code=422)
        try:
            payload = response.json()
        except ValueError as error:
            raise GatewayOnboardingError("gateway returned an invalid simulation") from error
        if (
            not isinstance(payload, dict)
            or payload.get("status") not in {"RESOLVED", "OUT_OF_SCOPE", "UNCLEAR"}
            or not isinstance(payload.get("reply"), str)
            or not isinstance(payload.get("source"), str)
        ):
            raise GatewayOnboardingError("gateway returned an invalid simulation")
        raw_slots = payload.get("slots")
        slots = (
            {str(key)[:40]: str(value)[:120] for key, value in raw_slots.items()}
            if isinstance(raw_slots, dict)
            else {}
        )
        return GatewaySimulationResult(
            status=payload["status"],
            reply=payload["reply"][:1000],
            source=payload["source"][:32],
            capability_id=(
                str(payload["capability_id"])[:120]
                if payload.get("capability_id")
                else None
            ),
            capability_title=(
                str(payload["capability_title"])[:160]
                if payload.get("capability_title")
                else None
            ),
            action=str(payload["action"])[:120] if payload.get("action") else None,
            requires_confirmation=payload.get("requires_confirmation") is True,
            slots=slots,
        )
