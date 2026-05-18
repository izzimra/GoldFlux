# Project Structure

Expected layout (to be updated as scaffolding progresses):

```
GoldFlux/
├── .kiro/
│   ├── specs/              # Feature specifications
│   └── steering/           # AI steering rules
├── backend/                # Django project
│   ├── config/             # Django settings, urls, celery config
│   ├── prices/             # Gold price data app (models, views, serializers, tasks)
│   ├── predictions/        # ML predictions app
│   └── manage.py
├── frontend/               # Next.js project
│   ├── src/
│   │   ├── app/            # Next.js app router pages
│   │   ├── components/     # React components (charts, panels)
│   │   └── lib/            # API client, utilities
│   ├── tailwind.config.js
│   └── package.json
├── ml/                     # ML model training scripts and artifacts
├── docker-compose.yml      # Local dev environment (Postgres, Redis)
└── requirements.txt        # Python dependencies
```

## Conventions
- Django apps are feature-scoped (prices, predictions)
- Frontend uses Next.js App Router
- ML model artifacts stored on filesystem with date-versioned filenames
- API versioned under /api/v1/
