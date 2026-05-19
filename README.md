# GoldFlux

Gold Price Prediction & Market Intelligence — a full-stack web application that aggregates historical gold market data, trains ML models to forecast future prices, integrates real-time financial news with sentiment analysis, and presents everything on an interactive dashboard.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Django](https://img.shields.io/badge/Django-5.x-green)
![Next.js](https://img.shields.io/badge/Next.js-14-black)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Historical Gold Price Charts** — Interactive ApexCharts visualization with 1M/3M/6M/1Y/5Y range selectors and OHLCV tooltips
- **30-Day Price Predictions** — ML-powered forecasts with 95% confidence interval bands
- **Market Insights Panel** — Live gold news from Marketaux API with sentiment badges (positive/neutral/negative)
- **Model Transparency** — Training date, MAE, RMSE, and model version displayed on dashboard
- **Automated Pipelines** — Daily data ingestion, model retraining, and news fetching via Celery Beat
- **Responsive Design** — Desktop sidebar + mobile-first layout with Tailwind CSS

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Next.js (3000) │────▶│  Django API (8000)│────▶│  PostgreSQL │
│  React + Tailwind│     │  DRF + Celery     │     │  (or SQLite)│
└─────────────────┘     └──────────────────┘     └─────────────┘
                              │       │
                              ▼       ▼
                        ┌─────────┐  ┌──────────────┐
                        │  Redis  │  │  yfinance    │
                        │ (cache) │  │  Marketaux   │
                        └─────────┘  └──────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Redis (install via `brew install redis` on macOS)
- A [Marketaux](https://www.marketaux.com/) API key (free tier works)

### 1. Clone & Install

```bash
git clone https://github.com/izzimra/GoldFlux.git
cd GoldFlux

# Backend
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

### 2. Configure Environment

Create `backend/.env`:

```env
NEWS_API_KEY=your-marketaux-api-token
```

That's the only required variable. Optional overrides:

```env
# NEWS_API_BASE_URL=https://api.marketaux.com
# NEWS_API_KEYWORDS=gold,XAU,commodities
# NEWS_FETCH_INTERVAL_HOURS=4
# INGESTION_TIME=00:30
# REDIS_URL=redis://localhost:6379/0
# POSTGRES_DB=goldflux
# CORS_ALLOWED_ORIGINS=http://localhost:3000
```

### 3. Start Services

```bash
# Terminal 1: Redis
redis-server

# Terminal 2: Backend
cd backend
python3 manage.py migrate
python3 manage.py seed_data   # Ingests prices, trains model, fetches news
python3 manage.py runserver

# Terminal 3: Frontend
cd frontend
npm run dev
```

### 4. Open Dashboard

Visit **http://localhost:3000**

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/prices/historical` | GET | Historical gold prices (supports `start_date`, `end_date`) |
| `/api/v1/prices/predictions` | GET | 30-day price forecasts with confidence intervals |
| `/api/v1/model/metadata` | GET | Current model training metrics |
| `/api/v1/news/gold/` | GET | Cached gold news with sentiment (supports `limit`) |

## Project Structure

```
GoldFlux/
├── backend/
│   ├── config/          # Django settings, Celery, middleware, URLs
│   ├── prices/          # Gold price models, views, ingestion tasks
│   ├── predictions/     # ML training, prediction generation, API
│   ├── news/            # Marketaux integration, caching, sentiment
│   └── manage.py
├── frontend/
│   ├── src/
│   │   ├── app/         # Next.js App Router (dashboard page)
│   │   ├── components/  # Charts, panels, badges, error states
│   │   └── lib/         # API client, hooks
│   └── package.json
├── requirements.txt
└── README.md
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React, Next.js 14, Tailwind CSS, ApexCharts |
| Backend | Python 3.11+, Django 5, Django REST Framework |
| ML | Scikit-Learn (Ridge regression + polynomial features) |
| Data | yfinance (GC=F Gold Futures ticker) |
| News | Marketaux API |
| Task Queue | Celery + Redis |
| Database | PostgreSQL (production) / SQLite (local dev) |
| Cache | Redis |

## Running Tests

```bash
# Backend (214 tests)
cd backend && python3 -m pytest

# Frontend (176 tests)
cd frontend && npm test
```

## Celery Pipelines

When running with Celery Beat in production:

- **Daily at 00:30 UTC**: `ingest_gold_prices` → `train_model` → `generate_predictions`
- **Every 4 hours**: `fetch_news` (independent from price pipeline)

For local development, `python3 manage.py seed_data` runs the full pipeline synchronously without needing Celery workers.

## License

MIT
