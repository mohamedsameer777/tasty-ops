Tasty Ops — Smart Operations Platform for Small Food Businesses

A multi-tenant, mobile-friendly billing + inventory + demand-forecasting + AI-agent platform built for street-food stalls and small restaurants. Every sale is logged as structured data, and that data powers stock deduction, next-day demand forecasts, automatic supplier reorder messages, and weekly forecast-accuracy reports.

Originally built for Tasty Zone (a burger and momo stall in Chennai), and now designed so any number of shops can sign up and use the same deployment without ever seeing each other's data.

Table of Contents
Features
How It Works
Tech Stack
Project Structure
Data Model
Getting Started
Environment Variables
Loading Data
Web Pages
API Reference
Automation and Scheduled Jobs
Deployment
Design Notes
Security Notes
Roadmap
Features

Billing and ordering

Fast order-entry screen (installable as a PWA with a service worker and manifest)
Voice ordering: say or type "two chicken burgers extra cheese, one veg momo fried" and it is parsed into line items using fuzzy matching against the shop's real menu
Item modifiers: parcel (+₹5), fried (+₹20), extra cheese (+₹20), applied only where the menu item supports them
Optional customer name and phone, plus daily-resetting order and bill numbers ("Bill 3")
Payment methods: Cash, GPay/UPI, and Split (validated so cash + UPI equals the total)
UPI QR code at checkout, generated from the shop's UPI ID
Send the bill to the customer on WhatsApp, with the shop's Google review, Instagram and YouTube links attached

Inventory

Ingredients with current stock, reorder threshold and supplier contact
Recipe mapping (menu item → ingredient quantities)
Automatic stock deduction whenever a bill is generated (stock is allowed to go negative on purpose, because that is the signal the reorder agent acts on)

Forecasting and agents

Per-item XGBoost demand forecasts using day-of-week, weekend flag and weather (Open-Meteo, no API key needed)
Reorder agent: decides sufficient, low_stock or critical for each ingredient, logs its reasoning, and messages the supplier only when needed
Anomaly agent: compares forecast vs. actual sales and flags over-forecast (wastage risk) and under-forecast (lost-sales risk) days
Weekly summary agent: writes a plain-English forecast-accuracy report

Dashboards

Today's sales, history, and analytics
Daily revenue target with a progress bar and streak counter

Platform

Self-serve shop signup (creates the shop and its owner account together)
Strict multi-tenant isolation on every API endpoint
Session and JWT authentication
Optional Cloudinary storage for menu photos and shop logos
How It Works
 Order entry (touch / voice)
          │
          ▼
  Order ──► Bill (immutable) ──► Ingredient stock auto-deducted
          │
          ▼
  Sales history (OrderItem)
          │
          ├──► Forecasting (XGBoost + weather) ──► DemandForecast
          │                                             │
          │                                             ▼
          │                                    Reorder agent
          │                          sufficient / low_stock / critical
          │                                             │
          │                            AgentLog  +  Supplier message
          │                                    (WhatsApp → email fallback)
          ▼
  Anomaly agent (forecast vs. actual) ──► DemandAnomaly ──► Weekly summary report
Reorder agent logic

For each ingredient, the agent computes projected_stock = current_stock − forecasted_demand and branches:

Condition	Decision	Action
projected_stock <= 0	critical	Message sent to the supplier immediately
Current or projected stock at or below the reorder threshold	low_stock	Message drafted for review, not auto-sent
Otherwise	sufficient	Logged only

Suggested order quantity is (threshold × 2) − projected_stock. Every decision is saved in AgentLog with plain-English reasoning.

Forecasting logic
14 or more days of history for an item: train a small XGBoost regressor on day_of_week, is_weekend, temp_max and precipitation
Fewer than 14 days: fall back to a rolling average
No history: predict 0
If the weather API is unreachable, the forecast continues without weather features instead of failing
Anomaly agent logic

After a forecast date passes, actual quantities are backfilled from billing data. Any item-day with variance beyond ±20% is flagged as over-forecast or under-forecast.

Tech Stack
Layer	Technology
Backend	Python, Django 5, Django REST Framework
Auth	Django sessions + SimpleJWT
Database	PostgreSQL (SQLite for quick local trials)
ML	XGBoost, scikit-learn, pandas, NumPy
Weather data	Open-Meteo (free, keyless)
Background jobs	Celery + Redis + django-celery-beat
Messaging	Twilio WhatsApp API, Django email backend (fallback)
Static and media	WhiteNoise, Cloudinary (optional)
Serving	Gunicorn
Frontend	Django templates, vanilla JS, PWA (service worker + manifest), qrcode.js
Project Structure
tasty-ops/
├── manage.py
├── requirements.txt
├── .env.example
├── tasty_ops/                  # Project config
│   ├── settings.py             # DB, auth, Celery beat schedule, Twilio, Cloudinary
│   ├── celery.py               # Celery app
│   ├── urls.py                 # Page routes + API mount + JWT endpoints
│   └── storage.py
└── billing/                    # Main app
    ├── models.py               # Shop, Membership, MenuItem, Order, OrderItem, Bill,
    │                           # Ingredient, RecipeMap, DemandForecast, AgentLog,
    │                           # DemandAnomaly, WeeklySummaryReport
    ├── views.py                # DRF viewsets (orders, bills, inventory, agents)
    ├── dashboard_views.py      # HTML pages, signup, /run-daily-jobs/, shop settings
    ├── serializers.py
    ├── tenancy.py              # TenantScopedMixin: per-shop data isolation
    ├── voice_parsing.py        # Spoken order text → structured line items
    ├── forecasting.py          # XGBoost + weather demand forecasting
    ├── agents.py               # Reorder decision agent
    ├── anomaly_agent.py        # Forecast-vs-actual anomaly + weekly summary agent
    ├── notifications.py        # Twilio WhatsApp + email sending
    ├── tasks.py                # Celery tasks (nightly forecast, reorder, anomaly, weekly)
    ├── forms.py                # Shop signup form
    ├── admin.py
    ├── migrations/
    ├── templates/              # login, signup, order_entry, dashboard, history, analytics
    ├── static/billing/         # sw.js, manifest.json, icons, qrcode.min.js
    └── management/commands/    # CLI tools (see below)
Data Model
Model	Purpose
Shop	A tenant: name, slug, logo, location, UPI ID, social links, daily revenue target
Membership	Links a user to their shop with a role (owner / staff)
MenuItem	Sellable item with price, optional cost price, image, fried/cheese options
Order	An open basket of items, with a daily-resetting order number
OrderItem	Item + quantity + modifiers, with a price snapshot in unit_price
Bill	Finalized bill: subtotal, tax, total, payment method, cash/UPI split
Ingredient	Stock item with unit, current stock, reorder threshold, supplier contact
RecipeMap	Quantity of an ingredient used per unit of a menu item
DemandForecast	Predicted (and later actual) quantity per item per date
AgentLog	The reorder agent's decision, reasoning, and message for each ingredient
DemandAnomaly	Per item-day variance and flag (normal / over / under)
WeeklySummaryReport	Plain-English weekly report
Getting Started
Prerequisites
Python 3.10+
PostgreSQL (or use SQLite for a quick trial)
Redis (only needed if you run Celery locally)
Installation
bash
git clone https://github.com/<your-username>/tasty-ops.git
cd tasty-ops

python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: at minimum set SECRET_KEY, and either DB_* values or USE_SQLITE=True

If you use PostgreSQL, create the database first:

bash
createdb tasty_ops
# or: psql -U postgres -c "CREATE DATABASE tasty_ops;"

Then:

bash
python3 manage.py migrate
python3 manage.py createsuperuser     # optional, for /admin/
python3 manage.py runserver

Open http://127.0.0.1:8000/accounts/signup/ to create your first shop and owner account, then go to /billing/ to start taking orders.

Environment Variables
Variable	Default	Description
SECRET_KEY	insecure dev key	Django secret key. Always set this in production
DEBUG	True	Set to False in production
ALLOWED_HOSTS	localhost,127.0.0.1	Comma-separated hostnames
CSRF_TRUSTED_ORIGINS	empty	Your https:// domain(s) in production
DATABASE_URL	empty	If set, overrides all other DB settings (used on Render/Railway)
USE_SQLITE	False	Use a local SQLite file instead of PostgreSQL
DB_NAME DB_USER DB_PASSWORD DB_HOST DB_PORT	tasty_ops / postgres / postgres / localhost / 5432	PostgreSQL connection
DAILY_JOBS_SECRET	empty	Shared secret for /run-daily-jobs/
CELERY_BROKER_URL CELERY_RESULT_BACKEND	redis://localhost:6379/0	Celery/Redis
FORECAST_HOUR FORECAST_MINUTE	21 0	Nightly forecast time
REORDER_AGENT_HOUR REORDER_AGENT_MINUTE	21 15	Nightly reorder agent time
ANOMALY_CHECK_HOUR ANOMALY_CHECK_MINUTE	23 0	Nightly anomaly check time
WEEKLY_SUMMARY_HOUR WEEKLY_SUMMARY_MINUTE WEEKLY_SUMMARY_DAY	8 0 1	Weekly report (day 1 = Monday)
EMAIL_BACKEND	console backend	Set to an SMTP backend for real email
DEFAULT_FROM_EMAIL	tastyzone@example.com	Sender address for supplier emails
TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_WHATSAPP_FROM	empty	WhatsApp messaging. Leave blank to fall back to email
CLOUDINARY_CLOUD_NAME CLOUDINARY_API_KEY CLOUDINARY_API_SECRET	empty	Persistent image storage. If unset, images use the local filesystem
Twilio WhatsApp setup (optional)
Sign up at https://console.twilio.com
Go to Messaging → Try it out → Send a WhatsApp message (sandbox)
Copy your Account SID and Auth Token into .env
Set TWILIO_WHATSAPP_FROM to the sandbox number shown there
Each recipient must send the sandbox join code to that number once (sandbox limitation)

For real customers you need a Meta-approved WhatsApp Business sender via Twilio, and business-initiated messages such as bills must use pre-approved message templates.

Loading Data

Management commands accept --shop <slug> (optional if only one shop exists).

bash
# Load the Tasty Zone menu (burgers, momos, rolls, pasta, etc.)
python3 manage.py load_tasty_zone_menu --shop <slug>

# Backfill synthetic sales so the forecaster has something to train on
python3 manage.py generate_synthetic_sales --shop <slug> --days 60 --seed 42

# Run the pipeline manually
python3 manage.py run_forecast          --shop <slug> [--date YYYY-MM-DD]
python3 manage.py run_reorder_agent     --shop <slug> [--date YYYY-MM-DD]
python3 manage.py run_anomaly_agent     --shop <slug>
python3 manage.py generate_weekly_summary --shop <slug> [--week-start YYYY-MM-DD]

generate_synthetic_sales does not touch ingredient stock. It exists only to bootstrap history. Replace it with real billing data once you have a few weeks of sales.

Web Pages
URL	Description
/accounts/signup/	Create a shop and owner account
/accounts/login/	Log in
/billing/	Order entry (touch and voice)
/dashboard/	Today's sales, revenue target and streak
/history/	Bill history
/analytics/	Sales analytics
/shop-settings/	POST endpoint for logo, location, UPI ID, social links
/admin/	Django admin
API Reference

All endpoints live under /api/, require authentication (session or JWT), and are automatically scoped to the caller's shop. Lists are paginated (50 per page).

Authentication
Method	URL	Description
POST	/api/token/	Obtain access + refresh JWT (access: 8 h, refresh: 7 d)
POST	/api/token/refresh/	Refresh the access token

Use the token as Authorization: Bearer <access>.

Menu and orders
Method	URL	Description
GET/POST	/api/menu-items/	List / create menu items
PATCH	/api/menu-items/{id}/	Update price, toggle active
GET/POST	/api/orders/	List (filter with ?status=open) / start an order
POST	/api/orders/{id}/add_items/	Add one item or a list of items
POST	/api/orders/{id}/set_item_quantity/	Change a line's quantity
POST	/api/orders/{id}/voice_add/	Add items from spoken/typed text
POST	/api/orders/{id}/toggle_item_parcel/	Toggle parcel on a line
POST	/api/orders/{id}/generate_bill/	Finalize into a bill (tax_rate, payment_method, cash_amount, upi_amount)
Bills and reporting
Method	URL	Description
GET	/api/bills/	Bill history
GET	/api/bills/today/	Today's bills and running total
GET	/api/bills/history/	Day-by-day summary
GET	/api/bills/analytics/	Analytics data
GET	/api/bills/daily_goal/	Revenue target progress and streak
GET	/api/bills/revenue_summary/	Revenue summary
POST	/api/bills/{id}/send_whatsapp/	Send the bill to the customer on WhatsApp
Inventory and agents
Method	URL	Description
GET/POST	/api/ingredients/	Manage ingredients
GET	/api/ingredients/low_stock/	Ingredients at or below threshold
GET/POST	/api/recipe-map/	Menu item → ingredient recipes
GET	/api/forecasts/	Demand forecasts
GET	/api/agent-logs/	Reorder agent decisions and reasoning
POST	/api/agent-logs/{id}/send_whatsapp/	Send a drafted supplier message
GET	/api/anomalies/	Forecast vs. actual anomalies
GET	/api/weekly-summaries/	Weekly summary reports
Example: order → bill
bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"owner","password":"secret"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access'])")
AUTH="Authorization: Bearer $TOKEN"

# 1. Add a menu item
curl -X POST http://127.0.0.1:8000/api/menu-items/ -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"name":"Chicken Momo (6 PCS)","category":"momo","price":"110.00","supports_fried_option":true}'

# 2. Start an order
curl -X POST http://127.0.0.1:8000/api/orders/ -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"table_or_token":"T1"}'

# 3. Add items
curl -X POST http://127.0.0.1:8000/api/orders/1/add_items/ -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"menu_item":1,"quantity":2,"is_fried":true}'

# 4. Generate the bill (split payment example)
curl -X POST http://127.0.0.1:8000/api/orders/1/generate_bill/ -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"tax_rate":"5.00","payment_method":"split","cash_amount":"100.00","upi_amount":"175.00"}'

# 5. Check today's sales
curl http://127.0.0.1:8000/api/bills/today/ -H "$AUTH"
Automation and Scheduled Jobs

There are two ways to run the nightly pipeline.

Option A: Celery + Redis (self-hosted)

Default schedule (Asia/Kolkata), editable at runtime in Django admin under Periodic tasks:

Task	Default time
run_nightly_forecast	21:00 daily
run_nightly_reorder_agent	21:15 daily
run_nightly_anomaly_check	23:00 daily
run_weekly_summary_report	Monday 08:00
bash
redis-server
celery -A tasty_ops worker -l info
celery -A tasty_ops beat -l info
Option B: External cron (free-tier hosting, no background worker)

Point a free scheduler such as cron-job.org at:

GET https://<your-domain>/run-daily-jobs/?token=<DAILY_JOBS_SECRET>

Once a day this runs forecasting, the reorder agent and the anomaly check for every active shop, plus the weekly summary on Mondays. Each step is isolated, so one failure does not stop the others.

Deployment

The project is set up for platforms like Render or Railway:

Provision a PostgreSQL database (DATABASE_URL is picked up automatically)
Set SECRET_KEY, DEBUG=False, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, DAILY_JOBS_SECRET
(Recommended) set the CLOUDINARY_* variables, because free-tier disks are ephemeral and uploaded photos would otherwise be lost
Build command:
bash
   pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
Start command:
bash
   gunicorn tasty_ops.wsgi
Configure the external cron job from Option B above

HTTPS termination at the proxy is already handled (SECURE_PROXY_SSL_HEADER).

Design Notes
Price snapshots. OrderItem.unit_price stores the price at the time of sale, so later menu price changes never rewrite history.
Bills are the system of record. A bill is created once and treated as immutable. Stock deduction, forecasting and anomaly detection all derive from it.
Stock may go negative. Billing is never blocked by inventory. A negative number is exactly what triggers a critical reorder decision.
Tenant isolation by construction. TenantScopedMixin filters every queryset by the user's shop, stamps shop on created rows, and scopes related-field choices (for example, menu item IDs on an order), so cross-shop access returns 404 instead of leaking data.
Explainable agents. Every reorder decision, including "do nothing", is stored with its reasoning.
Graceful degradation. Missing weather data, missing Twilio credentials, or too little sales history never crash the pipeline. Each has a fallback.
A stale-cache gotcha worth remembering. DRF's prefetch_related cache does not refresh after creating related rows within the same request, so add_items re-fetches the order before serializing its response.
Security Notes
Never commit .env. Rotate any credential that has ever been committed.
Use a strong random DAILY_JOBS_SECRET. It protects /run-daily-jobs/.
/bootstrap-admin/ creates a superuser through a URL (token-protected) for hosts without shell access. Because it accepts a password in the query string, remove that route once your admin account exists.
Set DEBUG=False and a unique SECRET_KEY in production.
The Twilio WhatsApp sandbox is for testing only.
Roadmap
 Staff role permissions (the Membership.role field is already in place)
 Automated test suite (currently a placeholder)
 Per-ingredient supplier lead times for smarter reorder quantities
 Per-shop forecast coordinates (currently fixed to Chennai)
 Margin and wastage analytics using cost_price
 WhatsApp Business templates for production bill sending
Author

S. Mohamed Sameer, @mohammedsameer777

License

Add a license of your choice (for example MIT) before publishing.
