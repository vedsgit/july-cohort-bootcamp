from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .schemas import TrustedActor


@dataclass(frozen=True)
class SeedOrder:
    tenant_id: str
    order_id: str
    status: str
    refundable_balance: Decimal


# Catalog created before any agent turn — same idea as data the frontend already has.
SEED_ORDERS: tuple[SeedOrder, ...] = (
    SeedOrder(
        tenant_id="tenant_acme",
        order_id="ord_A100",
        status="delivered",
        refundable_balance=Decimal("499.00"),
    ),
    SeedOrder(
        tenant_id="tenant_other",
        order_id="ord_B200",
        status="shipped",
        refundable_balance=Decimal("220.00"),
    ),
)


def orders_by_key() -> dict[tuple[str, str], SeedOrder]:
    return {(o.tenant_id, o.order_id): o for o in SEED_ORDERS}


@dataclass(frozen=True)
class FrontendSession:
    """
    What the frontend / API gateway already knows after auth.

    Tenant and actor identity arrive here — never from model output.
    """

    actor_id: str
    role: str
    tenant_id: str
    session_id: str = "sess_demo_acme"

    def to_trusted_actor(self) -> TrustedActor:
        return TrustedActor(
            actor_id=self.actor_id,
            role=self.role,
            tenant_id=self.tenant_id,
        )


def default_frontend_session() -> FrontendSession:
    """Logged-in Acme support agent (seeded demo identity)."""
    return FrontendSession(
        actor_id="agent_42",
        role="support_agent",
        tenant_id="tenant_acme",
        session_id="sess_acme_agent_42",
    )
