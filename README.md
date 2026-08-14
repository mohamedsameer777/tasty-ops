# Tasty Zone Smart Ops — Phase 1: Billing System MVP

Every real sale gets logged as structured data — `MenuItem` → `Order` → `OrderItem` → `Bill`.
This is the foundation everything else (inventory, forecasting, agents) builds on.

## What's here

- **`billing/models.py`** — `MenuItem`, `Order`, `OrderItem`, `Bill`
- **`billing/views.py`** — the order → bill workflow (see endpoints below)
- **`billing/serializers.py`**, **`billing/admin.py`**, **`billing/urls.py`**
- **`tasty_ops/settings.py`** — Postgres by default, reads config from `.env`

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — at minimum set SECRET_KEY, and either:
#   - fill in DB_NAME/DB_USER/DB_PASSWORD for a real Postgres db, or
#   - set USE_SQLITE=True to skip Postgres for now and just try the API

python3 manage.py migrate
python3 manage.py createsuperuser   # for /admin/
python3 manage.py runserver
```

If using Postgres, create the database first:
```bash
createdb tasty_ops
# or: psql -U postgres -c "CREATE DATABASE tasty_ops;"
```

## Endpoints

| Method | URL | What it does |
|---|---|---|
| GET/POST | `/api/menu-items/` | list / create menu items |
| PATCH | `/api/menu-items/{id}/` | update price, toggle active |
| POST | `/api/orders/` | start a new order (`table_or_token` optional) |
| GET | `/api/orders/?status=open` | list orders, filterable by status |
| POST | `/api/orders/{id}/add_items/` | add item(s) to an open order |
| POST | `/api/orders/{id}/generate_bill/` | finalize order → bill (accepts `tax_rate`) |
| GET | `/api/bills/today/` | today's bills + running total sales |
| GET | `/api/bills/` | full bill history |

Admin UI at `/admin/` — fastest way to eyeball data while testing.

## Try it end-to-end

```bash
# 1. Add a menu item
curl -X POST http://127.0.0.1:8000/api/menu-items/ \
  -H "Content-Type: application/json" \
  -d '{"name":"Chicken 65","category":"starter","price":"180.00","cost_price":"90.00"}'

# 2. Start an order
curl -X POST http://127.0.0.1:8000/api/orders/ \
  -H "Content-Type: application/json" -d '{"table_or_token":"T1"}'

# 3. Add items to it (order id from step 2)
curl -X POST http://127.0.0.1:8000/api/orders/1/add_items/ \
  -H "Content-Type: application/json" -d '{"menu_item":1,"quantity":2}'

# 4. Generate the bill
curl -X POST http://127.0.0.1:8000/api/orders/1/generate_bill/ \
  -H "Content-Type: application/json" -d '{"tax_rate":"5.00"}'

# 5. Check today's sales
curl http://127.0.0.1:8000/api/bills/today/
```

## Design notes (worth knowing for later phases / interviews)

- **`OrderItem.unit_price` is a price snapshot**, not a live reference to `MenuItem.price`. If you raise the price of Chicken 65 next week, last week's bills stay historically accurate.
- **`Bill` is effectively immutable** once created — it's the system of record for everything downstream (inventory deduction in Phase 2, forecasting in Phase 3).
- **`add_items` accepts a single item or a list**, so the frontend can either punch items one at a time or submit a whole basket at once.
- I tested the full order→bill flow end-to-end while building this and caught a real bug: DRF's `prefetch_related` cache doesn't auto-refresh after you create new related rows inside the same request, so the `add_items` response was silently showing an empty item list right after adding items. Fixed by re-fetching the order before serializing the response — worth remembering, it's an easy one to reintroduce in Phase 2/3 endpoints.

## Not done yet (by design — later phases)

- No JWT auth yet (Phase 1 is wide open — `AllowAny`). Auth gets layered in once the core flow is solid.
- No inventory/stock deduction (Phase 2).
- No frontend beyond Django admin — pick React or Flutter when you're ready and I'll build the order-entry screen against these exact endpoints.

---

**Next up: Phase 2 — Inventory Layer.** Say the word and we'll add `Ingredient` + `RecipeMap`, and wire stock auto-deduction into `generate_bill`.
