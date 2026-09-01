"""Stripe billing: 30-day free trial then a recurring subscription.

Flow:
  - POST /billing/checkout  → Stripe Checkout (subscription, trial_period_days,
    card required up front). Returns a hosted-checkout URL the web redirects to.
  - POST /billing/portal    → Stripe Billing Portal (manage card / cancel).
  - GET  /billing/status    → the subscription state the paywall reads.
  - POST /billing/webhook   → Stripe → us (signature-verified, no user auth).

The user row mirrors Stripe state; the webhook is the source of truth. The
checkout response is optimistic only — we never trust the browser for access.
"""
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status

from adelia.auth import get_current_user_id, local_trial_end
from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import User

router = APIRouter(prefix="/billing", tags=["billing"])

# Statuses that grant product access. Stripe keeps a subscription "trialing"
# until the trial ends, then "active" once the first invoice is paid.
ACTIVE_STATUSES = {"trialing", "active"}


def _require_stripe() -> None:
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing not configured",
        )
    stripe.api_key = settings.stripe_secret_key


def _ts(epoch: int | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch else None


def _remaining_trial_days(user: User) -> int:
    """Whole days left of the card-free trial, rounded up, 0 when none.

    Rounded UP so a mother who subscribes with 4 hours left is not charged
    those 4 hours; the cost of the rounding is at most one day of a 8 EUR
    plan, and the alternative reads as a penalty for converting early.
    """
    end = local_trial_end(user.subscription_status or "none", user.created_at)
    if end is None:
        return 0
    seconds = (end - datetime.now(timezone.utc)).total_seconds()
    if seconds <= 0:
        return 0
    return max(1, -(-int(seconds) // 86400))


async def _load_user(user_id: UUID) -> User:
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return user


def _status_payload(user: User) -> dict[str, Any]:
    """What the paywall, the billing page and the Settings section all read.

    The card-free trial (audit 4.7) is reported through the SAME keys as a
    Stripe trial — status "trialing", active true, trial_end the day it runs
    out — so no screen needs to know which of the two it is looking at. Two
    keys carry what does differ:

      trial_source  "stripe" | "local" | null. "local" is a trial this server
                    granted, which Stripe has never heard of.
      can_manage    whether there is a Stripe customer behind this account,
                    i.e. whether POST /billing/portal has anything to open.
                    Settings shows "Manage subscription" when true and
                    "Subscribe" when false, instead of a button that 400s.
    """
    stored = user.subscription_status or "none"
    local_end = local_trial_end(stored, user.created_at)
    local_active = local_end is not None and local_end > datetime.now(timezone.utc)

    if stored in ACTIVE_STATUSES:
        status_value, active, trial_source = stored, True, (
            "stripe" if user.trial_end else None
        )
        trial_end = user.trial_end
    elif local_active:
        status_value, active, trial_source = "trialing", True, "local"
        trial_end = local_end
    else:
        status_value, active, trial_source = stored, False, None
        trial_end = user.trial_end

    return {
        "status": status_value,
        "active": active,
        "plan": user.subscription_plan,
        "trial_end": trial_end.isoformat() if trial_end else None,
        "current_period_end": (
            user.current_period_end.isoformat() if user.current_period_end else None
        ),
        "trial_days": settings.stripe_trial_days,
        "trial_source": trial_source,
        "can_manage": bool(user.stripe_customer_id),
    }


@router.get("/status")
async def billing_status(
    user_id: Annotated[UUID, Depends(get_current_user_id)],
) -> dict[str, Any]:
    user = await _load_user(user_id)
    return _status_payload(user)


@router.post("/checkout")
async def create_checkout(
    user_id: Annotated[UUID, Depends(get_current_user_id)],
) -> dict[str, str]:
    _require_stripe()
    if not settings.stripe_price_id:
        raise HTTPException(status_code=503, detail="No price configured")

    user = await _load_user(user_id)

    # Already covered by STRIPE → nothing to buy; send them to manage instead.
    # An account inside its card-free trial is deliberately NOT blocked here:
    # the whole point of that trial is that she can subscribe whenever she
    # decides to, without waiting for it to run out (audit 4.7).
    if (user.subscription_status or "none") in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Subscription already active")

    # Reuse a Stripe customer per user so trials can't be farmed by re-checkout.
    customer_id = user.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            metadata={"user_id": str(user_id)},
        )
        customer_id = customer["id"]
        async with AsyncSessionLocal() as session:
            db_user = await session.get(User, user_id)
            db_user.stripe_customer_id = customer_id
            await session.commit()

    base = settings.adelia_app_url.rstrip("/")
    # Days of the card-free trial she has NOT used yet. Without this the two
    # trials stack: 30 free days on this server, then Stripe grants another 30
    # at checkout, and the first invoice lands on day 60 (audit 4.7). Stripe
    # rejects trial_period_days below 1, so 0 means "omit the key".
    subscription_data: dict[str, Any] = {"metadata": {"user_id": str(user_id)}}
    remaining = _remaining_trial_days(user)
    if remaining > 0:
        subscription_data["trial_period_days"] = remaining
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=str(user_id),
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        subscription_data=subscription_data,
        # A card at THIS point is not the wall the audit found: she is here
        # because she pressed "subscribe", after using the product for free.
        payment_method_collection="always",
        allow_promotion_codes=True,
        success_url=f"{base}/billing?checkout=success",
        cancel_url=f"{base}/billing?checkout=cancel",
    )
    return {"url": session["url"]}


@router.post("/portal")
async def create_portal(
    user_id: Annotated[UUID, Depends(get_current_user_id)],
) -> dict[str, str]:
    _require_stripe()
    user = await _load_user(user_id)
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account yet")
    base = settings.adelia_app_url.rstrip("/")
    portal = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{base}/dashboard",
    )
    return {"url": portal["url"]}


async def _apply_subscription(sub: dict[str, Any]) -> None:
    """Mirror a Stripe Subscription object onto the owning user row."""
    user_id_raw = (sub.get("metadata") or {}).get("user_id")
    customer_id = sub.get("customer")

    async with AsyncSessionLocal() as session:
        user = None
        if user_id_raw:
            try:
                user = await session.get(User, UUID(user_id_raw))
            except ValueError:
                user = None
        if user is None and customer_id:
            from sqlalchemy import select

            res = await session.execute(
                select(User).where(User.stripe_customer_id == customer_id)
            )
            user = res.scalar_one_or_none()
        if user is None:
            return  # unknown subscription — nothing to mirror

        user.subscription_status = sub.get("status") or "none"
        user.trial_end = _ts(sub.get("trial_end"))
        user.current_period_end = _ts(sub.get("current_period_end"))
        items = (sub.get("items") or {}).get("data") or []
        if items:
            price = items[0].get("price") or {}
            user.subscription_plan = price.get("nickname") or price.get("id")
        if customer_id and not user.stripe_customer_id:
            user.stripe_customer_id = customer_id
        await session.commit()


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict[str, bool]:
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    # stripe-python v8+ exposes errors at the top level (no stripe.error module).
    sig_error = getattr(stripe, "SignatureVerificationError", Exception)
    try:
        event = stripe.Webhook.construct_event(
            payload, sig, settings.stripe_webhook_secret
        )
    except (ValueError, sig_error):
        raise HTTPException(status_code=400, detail="Invalid signature")

    etype = event["type"]
    obj = event["data"]["object"]

    if etype in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        await _apply_subscription(obj)
    elif etype == "checkout.session.completed":
        # The session carries the subscription id; fetch it to get full state.
        sub_id = obj.get("subscription")
        if sub_id:
            stripe.api_key = settings.stripe_secret_key
            sub = stripe.Subscription.retrieve(sub_id)
            await _apply_subscription(sub)

    return {"received": True}
