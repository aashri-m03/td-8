from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uuid
import time
import base64

app = FastAPI(title="Orders API")

# ---------------------------
# Configuration
# ---------------------------

TOTAL_ORDERS = 54
RATE_LIMIT = 18
WINDOW_SECONDS = 10

# ---------------------------
# CORS
# ---------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# In-memory storage
# ---------------------------

# Idempotency-Key -> order
idempotency_store = {}

# ClientID -> timestamps
rate_limit_store = {}

# Fixed catalog IDs 1..54
ORDERS_CATALOG = [
    {
        "id": i,
        "item": f"order-{i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]


# ---------------------------
# Models
# ---------------------------

class OrderCreate(BaseModel):
    item: Optional[str] = "sample-order"


# ---------------------------
# Helpers
# ---------------------------

def encode_cursor(index: int) -> str:
    return base64.urlsafe_b64encode(
        str(index).encode()
    ).decode()


def decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0

    try:
        return int(
            base64.urlsafe_b64decode(
                cursor.encode()
            ).decode()
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid cursor"
        )


def enforce_rate_limit(
    client_id: str,
):
    now = time.time()

    timestamps = rate_limit_store.setdefault(
        client_id,
        []
    )

    cutoff = now - WINDOW_SECONDS

    timestamps[:] = [
        t for t in timestamps
        if t > cutoff
    ]

    if len(timestamps) >= RATE_LIMIT:
        retry_after = max(
            1,
            int(timestamps[0] + WINDOW_SECONDS - now + 0.999)
        )

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(retry_after)
            }
        )

    timestamps.append(now)


# ---------------------------
# Health endpoint
# ---------------------------

@app.get("/")
def health():
    return {
        "status": "ok"
    }


# ---------------------------
# Create order (Idempotent)
# ---------------------------

@app.post("/orders", status_code=201)
def create_order(
    payload: OrderCreate,
    x_client_id: str = Header(
        default="anonymous",
        alias="X-Client-Id"
    ),
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key"
    )
):
    enforce_rate_limit(x_client_id)

    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    order = {
        "id": str(uuid.uuid4()),
        "item": payload.item
    }

    idempotency_store[idempotency_key] = order

    return order


# ---------------------------
# Cursor Pagination
# ---------------------------

@app.get("/orders")
def list_orders(
    limit: int = 10,
    cursor: Optional[str] = None,
    x_client_id: str = Header(
        default="anonymous",
        alias="X-Client-Id"
    )
):
    enforce_rate_limit(x_client_id)

    if limit < 1:
        limit = 1

    start_index = decode_cursor(cursor)

    items = ORDERS_CATALOG[
        start_index:start_index + limit
    ]

    next_index = start_index + len(items)

    next_cursor = None

    if next_index < TOTAL_ORDERS:
        next_cursor = encode_cursor(next_index)

    return {
        "items": items,
        "next_cursor": next_cursor
    }