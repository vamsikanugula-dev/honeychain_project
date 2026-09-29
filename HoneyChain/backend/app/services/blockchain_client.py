"""The only HTTP boundary between HoneyChain and the existing Fabric service.

There is intentionally no route or frontend call that can POST an arbitrary
transaction.  Workflow services create durable outbox events, and this client
submits exactly those events to ``{BLOCKCHAIN_BASE_URL}/transactions``.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger("honeychain.blockchain")


class BlockchainClientError(RuntimeError):
    """A safe, structured failure from the external blockchain API."""

    def __init__(self, message: str, *, retryable: bool = True, status_code: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class BlockchainClient:
    """Small synchronous client for the existing ``/transactions`` API."""

    def __init__(self, settings: Settings | None = None, *, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._provided_client = client

    @property
    def transactions_url(self) -> str:
        return urljoin(self.settings.BLOCKCHAIN_BASE_URL.rstrip("/") + "/", "transactions")

    def _request(self, method: str, *, json_body: dict[str, Any] | None = None) -> Any:
        attempts = max(1, int(self.settings.BLOCKCHAIN_RETRY_ATTEMPTS))
        timeout_seconds = max(1, int(self.settings.BLOCKCHAIN_TIMEOUT_MS)) / 1000
        last_error: BlockchainClientError | None = None

        for attempt in range(1, attempts + 1):
            client = self._provided_client or httpx.Client(timeout=timeout_seconds)
            close_client = self._provided_client is None
            try:
                response = client.request(method, self.transactions_url, json=json_body)
                if response.status_code >= 400:
                    retryable = response.status_code >= 500 or response.status_code in (408, 429)
                    raise BlockchainClientError(
                        f"Blockchain service returned HTTP {response.status_code}",
                        retryable=retryable,
                        status_code=response.status_code,
                    )
                try:
                    return response.json()
                except ValueError as exc:
                    raise BlockchainClientError(
                        "Blockchain service returned a non-JSON response", retryable=False
                    ) from exc
            except BlockchainClientError as exc:
                last_error = exc
                logger.warning(
                    "Blockchain API request failed",
                    extra={
                        "method": method,
                        "attempt": attempt,
                        "attempts": attempts,
                        "status_code": exc.status_code,
                        "retryable": exc.retryable,
                    },
                )
                if not exc.retryable or attempt == attempts:
                    raise
            except httpx.HTTPError as exc:
                last_error = BlockchainClientError(
                    f"Blockchain service connection failed: {type(exc).__name__}", retryable=True
                )
                logger.warning(
                    "Blockchain API connection failed",
                    extra={"method": method, "attempt": attempt, "attempts": attempts, "error_type": type(exc).__name__},
                )
                if attempt == attempts:
                    raise last_error from exc
            finally:
                if close_client:
                    client.close()
            # A small bounded backoff keeps an unavailable service from being
            # hammered while still making an interactive retry useful.
            time.sleep(0.15 * attempt)

        raise last_error or BlockchainClientError("Blockchain request failed")

    @staticmethod
    def _transactions_from_body(body: Any) -> list[dict[str, Any]]:
        if isinstance(body, list):
            rows = body
        elif isinstance(body, dict):
            rows = body.get("transactions", body.get("data", body.get("items", [])))
        else:
            raise BlockchainClientError("Blockchain GET response has an invalid shape", retryable=False)
        if not isinstance(rows, list):
            raise BlockchainClientError("Blockchain GET response does not contain transactions", retryable=False)
        clean: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise BlockchainClientError("Blockchain GET response contains an invalid transaction", retryable=False)
            # Legacy ledger records may have a sparse payload, but their identity
            # must always be present before we show them as real blockchain data.
            if not isinstance(row.get("tx_id"), str) or not isinstance(row.get("tx_type"), str):
                raise BlockchainClientError("Blockchain transaction is missing tx_id or tx_type", retryable=False)
            clean.append(row)
        return clean

    def get_transactions(self) -> list[dict[str, Any]]:
        """Retrieve the real ledger records from the Fabric service."""
        return self._transactions_from_body(self._request("GET"))

    def create_transaction(self, *, tx_type: str, batch_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit one allow-listed outbox transaction and validate its reference."""
        if not tx_type or not batch_id or not isinstance(payload, dict):
            raise BlockchainClientError("Invalid blockchain transaction request", retryable=False)
        body = self._request(
            "POST",
            json_body={"tx_type": tx_type, "batch_id": batch_id, "payload": payload},
        )
        # Fabric deployments commonly return either the transaction itself or a
        # `{data: transaction}` envelope.  Both are real responses; anything
        # without a tx_id is not a confirmation and is deliberately refused.
        record = body.get("data", body) if isinstance(body, dict) else None
        if not isinstance(record, dict) or not isinstance(record.get("tx_id"), str) or not record["tx_id"].strip():
            raise BlockchainClientError("Blockchain POST response is missing tx_id", retryable=True)
        if record.get("tx_type") not in (None, tx_type):
            raise BlockchainClientError("Blockchain POST response has a mismatched tx_type", retryable=True)
        if record.get("batch_id") not in (None, batch_id):
            raise BlockchainClientError("Blockchain POST response has a mismatched batch_id", retryable=True)
        return record


__all__ = ["BlockchainClient", "BlockchainClientError"]
