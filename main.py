from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uuid
import time
import base64

app = FastAPI(title="Orders API")

# ==============================
# CORS
# ==============================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================
# Assignment Values
# ==============================
TOTAL_ORDERS = 54
RATE_LIMIT = 18
WINDOW = 10  # seconds

# ==============================
# In-memory Storage
# ==============================
orders_created = {}
rate_limit_data = {}

catalog = [
    {
        "id": i,
        "item": f"Order {i}",
        "price": i * 10
    }
    for i in range(1, TOTAL_ORDERS + 1)
]


# ==============================
# Request Model
# ==============================
class OrderRequest(BaseModel):
    item: str = "Sample Item"


# ==============================
# Rate Limiting Middleware
# ==============================
@app.middleware("http")
async def rate_limiter(request: Request, call_next):

    client_id = request.headers.get("X-Client-Id")

    if client_id:

        now = time.time()

        timestamps = rate_limit_data.setdefault(client_id, [])

        # Remove expired timestamps
        timestamps[:] = [
            t for t in timestamps
            if now - t < WINDOW
        ]

        if len(timestamps) >= RATE_LIMIT:

            retry_after = WINDOW - (now - timestamps[0])

            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded"
                },
                headers={
                    "Retry-After": str(max(1, int(retry_after)))
                },
            )

        timestamps.append(now)

    response = await call_next(request)
    return response


# ==============================
# Root
# ==============================
@app.get("/")
def home():
    return {
        "message": "Orders API Running"
    }


# ==============================
# Idempotent POST /orders
# ==============================
@app.post("/orders", status_code=201)
def create_order(
    order: OrderRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key")
):

    # Return existing order if key already exists
    if idempotency_key in orders_created:
        return orders_created[idempotency_key]

    new_order = {
        "id": str(uuid.uuid4()),
        "item": order.item
    }

    orders_created[idempotency_key] = new_order

    return new_order


# ==============================
# Cursor Pagination
# ==============================
@app.get("/orders")
def get_orders(
    limit: int = 10,
    cursor: Optional[str] = None
):

    start = 0

    if cursor:
        try:
            start = int(
                base64.urlsafe_b64decode(cursor.encode()).decode()
            )
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid cursor"
            )

    end = min(start + limit, TOTAL_ORDERS)

    items = catalog[start:end]

    next_cursor = None

    if end < TOTAL_ORDERS:
        next_cursor = base64.urlsafe_b64encode(
            str(end).encode()
        ).decode()

    return {
        "items": items,
        "next_cursor": next_cursor
    }