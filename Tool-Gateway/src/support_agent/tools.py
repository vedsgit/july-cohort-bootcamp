from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .contracts import OrderStatusInput, RefundInput
from .errors import ToolBoundaryError


@dataclass(frozen=True)
class StoredRefund:
    fingerprint: str
    result: dict[str, object]


@dataclass(frozen=True)
class SeededOrder:
    tenant_id: str
    order_id: str
    status: str
    refundable_balance: Decimal


DEFAULT_SEEDED_ORDERS: tuple[SeededOrder, ...] = (
    SeededOrder("tenant_acme", "ord_A100", "delivered", Decimal("499.00")),
    SeededOrder("tenant_other", "ord_B200", "shipped", Decimal("220.00")),
)


def default_idempotency_store_path() -> Path:
    """Project-local stand-in for a durable idempotency table (Redis/DB in prod)."""
    project_root = Path(__file__).resolve().parents[2]
    override = os.getenv("GOVERNED_IDEMPOTENCY_STORE")
    if override:
        return Path(override).expanduser().resolve()
    return project_root / "logs" / "idempotency_refunds.json"


class SupportToolBackend:
    """
    Deterministic fake backend used for live teaching and tests.

    Refund idempotency is remembered in a JSON file by default (classroom stand-in
    for a unique constraint / idempotency table in a real database).
    """

    def __init__(
        self,
        *,
        seeded_orders: tuple[SeededOrder, ...] | None = None,
        idempotency_store_path: str | Path | None = ...,  # type: ignore[assignment]
    ) -> None:
        if idempotency_store_path is ...:
            self.idempotency_store_path: Path | None = default_idempotency_store_path()
        elif idempotency_store_path is None:
            self.idempotency_store_path = None
        else:
            self.idempotency_store_path = Path(idempotency_store_path)

        self.refund_by_key: dict[str, StoredRefund] = {}
        self.refund_side_effect_count = 0
        orders = seeded_orders if seeded_orders is not None else DEFAULT_SEEDED_ORDERS
        self.orders: dict[tuple[str, str], SeededOrder] = {
            (o.tenant_id, o.order_id): o for o in orders
        }
        self._load_store()

    def get_order_status(
        self, request: OrderStatusInput, idempotency_key: str | None
    ) -> dict[str, object]:
        del idempotency_key
        order = self.orders.get((request.tenant_id, request.order_id))
        if order is None:
            raise ToolBoundaryError(
                "order_not_found",
                f"No order {request.order_id} for tenant {request.tenant_id}",
            )
        return {
            "order_id": order.order_id,
            "status": order.status,
            "refundable_balance": order.refundable_balance,
        }

    def issue_refund(
        self, request: RefundInput, idempotency_key: str | None
    ) -> dict[str, object]:
        if not idempotency_key:
            raise ToolBoundaryError(
                "idempotency_required",
                "idempotency key is required for refund writes",
            )

        fingerprint = self._fingerprint(request)
        existing = self.refund_by_key.get(idempotency_key)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise ToolBoundaryError(
                    "idempotency_conflict",
                    "idempotency key was reused with different arguments",
                )
            return dict(existing.result)

        result: dict[str, object] = {
            "refund_id": f"ref_{uuid4().hex[:10]}",
            "order_id": request.order_id,
            "amount": request.amount,
            "status": "accepted",
        }
        self.refund_by_key[idempotency_key] = StoredRefund(
            fingerprint=fingerprint,
            result=result,
        )
        self.refund_side_effect_count += 1
        self._save_store()
        return dict(result)

    def _load_store(self) -> None:
        path = self.idempotency_store_path
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        refunds = payload.get("refunds", {})
        if not isinstance(refunds, dict):
            return
        loaded: dict[str, StoredRefund] = {}
        for key, item in refunds.items():
            if not isinstance(item, dict):
                continue
            fingerprint = item.get("fingerprint")
            result = item.get("result")
            if isinstance(fingerprint, str) and isinstance(result, dict):
                loaded[str(key)] = StoredRefund(fingerprint=fingerprint, result=result)
        self.refund_by_key = loaded
        count = payload.get("side_effect_count")
        if isinstance(count, int) and count >= 0:
            self.refund_side_effect_count = count
        else:
            self.refund_side_effect_count = len(loaded)

    def _save_store(self) -> None:
        path = self.idempotency_store_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "side_effect_count": self.refund_side_effect_count,
            "refunds": {
                key: {
                    "fingerprint": stored.fingerprint,
                    "result": stored.result,
                }
                for key, stored in self.refund_by_key.items()
            },
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)

    @staticmethod
    def _fingerprint(request: RefundInput) -> str:
        payload = request.model_dump(mode="json")
        return "|".join(
            f"{key}={payload[key]}"
            for key in ("tenant_id", "order_id", "amount", "reason")
        )
