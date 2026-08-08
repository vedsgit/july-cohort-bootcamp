from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import OrderStatusInput, RefundInput
from .errors import ToolBoundaryError


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
    def __init__(
        self,
        *,
        seeded_orders: tuple[SeededOrder, ...] | None = None,
        idempotency_store_path: str | Path | None | Any = ...,
    ) -> None:
        if idempotency_store_path is ...:
            self.idempotency_store_path: Path | None = default_idempotency_store_path()
        elif idempotency_store_path is None:
            self.idempotency_store_path = None
        else:
            self.idempotency_store_path = Path(idempotency_store_path)

        # Key → prior successful refund. Persist via _load_store / _save_store (TODO 3).
        self.refund_by_key: dict[str, dict[str, object]] = {}
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
        # TODO 3: make repeated execution return the original result.
        # Use idempotency_key + self.refund_by_key, then call self._save_store().
        # In prod this map is a DB/Redis unique constraint — here it's a JSON file.
        del idempotency_key
        result: dict[str, object] = {
            "refund_id": f"ref_{uuid4().hex[:10]}",
            "order_id": request.order_id,
            "amount": request.amount,
            "status": "accepted",
        }
        self.refund_side_effect_count += 1
        return result

    def _load_store(self) -> None:
        path = self.idempotency_store_path
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        refunds = payload.get("refunds", {})
        if isinstance(refunds, dict):
            self.refund_by_key = {
                str(key): value
                for key, value in refunds.items()
                if isinstance(value, dict)
            }
        count = payload.get("side_effect_count")
        if isinstance(count, int) and count >= 0:
            self.refund_side_effect_count = count

    def _save_store(self) -> None:
        path = self.idempotency_store_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "side_effect_count": self.refund_side_effect_count,
            "refunds": self.refund_by_key,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
