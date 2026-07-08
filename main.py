from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uuid
import time
import base64

app = FastAPI()

# --------------------
# CONFIG
# --------------------

TOTAL_ORDERS = 54
RATE_LIMIT = 18
WINDOW_SECONDS = 10

# --------------------
# CORS
# --------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------
# STORAGE
# --------------------

idempotency_store = {}
rate_limit_store = {}

ORDERS = [
    {
        "id": i,
        "item": f"order-{i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# --------------------
# MODELS
# --------------------

class OrderCreate(BaseModel):
    item: Optional[str] = "sample-order"

# --------------------
# HELPERS
# --------------------

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


def enforce_rate_limit(client_id: str):
    now = time.time()

    timestamps = rate_limit_store.setdefault(
        client_id,
        []
    )

    # remove old requests
    timestamps[:] = [
        ts for ts in timestamps
        if now - ts < WINDOW_SECONDS
    ]

    # limit exceeded
    if len(timestamps) >= RATE_LIMIT:

        retry_after = max(
            1,
            int(
                timestamps[0]
                + WINDOW_SECONDS
                - now
                + 0.999
            )
        )

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(retry_after)
            }
        )

    timestamps.append(now)

# --------------------
# HEALTH
# --------------------

@app.get("/")
def root():
    return {"status": "ok"}

# --------------------
# IDEMPOTENT POST
# --------------------

@app.post("/orders", status_code=201)
def create_order(
    payload: OrderCreate,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key"
    ),
    x_client_id: str = Header(
        default="anonymous",
        alias="X-Client-Id"
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

# --------------------
# CURSOR PAGINATION
# --------------------

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

    start = decode_cursor(cursor)

    items = ORDERS[start:start + limit]

    next_cursor = None
    next_index = start + len(items)

    if next_index < TOTAL_ORDERS:
        next_cursor = encode_cursor(next_index)

    return {
        "items": items,
        "next_cursor": next_cursor
    }