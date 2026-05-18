# Tech Stack

## Frontend
- React (Next.js) — SSR/SSG framework
- Tailwind CSS — utility-first styling
- ApexCharts — interactive data visualization

## Backend API
- Python 3.11+
- Django + Django REST Framework (DRF)
- Celery — async background task processing
- Redis — caching layer and Celery broker

## Database
- PostgreSQL — primary relational data store

## Machine Learning & Data
- Pandas — data manipulation
- Scikit-Learn / Prophet — time-series forecasting
- yfinance — market data source (GC=F Gold Futures ticker)

## Build & Commands

_To be defined once the project is scaffolded. Expected:_
- `pip install -r requirements.txt` — backend dependencies
- `npm install` — frontend dependencies
- `python manage.py runserver` — Django dev server
- `npm run dev` — Next.js dev server
- `celery -A config worker` — Celery worker
- `celery -A config beat` — Celery scheduler
- `python manage.py test` — backend tests
- `npm run test` — frontend tests
