# 🎬 Movie Web App API

RESTful movie management API built with **Flask**, featuring TMDB data synchronization, Google OAuth2 authentication, and admin dashboard.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | Flask 3.1 |
| Database | PostgreSQL + SQLAlchemy 2.0 |
| Auth | Google OAuth2 (Authlib) + JWT (PyJWT) |
| Validation | Pydantic v2 |
| Migration | Flask-Migrate (Alembic) |
| API Docs | Swagger UI (OpenAPI 3.0) |
| Deployment | Vercel |

---

## Features

- 🔐 **Google OAuth2** — Login with Google, JWT access + refresh tokens
- 🎥 **Movie CRUD** — Users & admins can create, update, soft-delete movies
- 🔄 **TMDB Sync** — Background sync (full + incremental via `/movie/changes`)
- 📹 **On-Demand Videos** — Trailers fetched & cached from TMDB on movie detail view
- 📋 **Wishlist** — Save movies to watchlist with scheduled watch dates
- 📊 **Admin Dashboard** — Analytics (total movies, users, wishlists, movies by source, top genres)
- 📄 **Swagger UI** — Interactive API docs at `/api/docs`
- 🌱 **CLI Seeder** — `flask seed-users` for initial data

---

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 14+

### Setup

```bash
# Clone
git clone https://github.com/haiser1/api_movie_ku.git
cd api_movie_ku

# Configure environment
cp .env.example .env
# Edit .env with your credentials (see Environment Variables below)
```

### Linux

```bash
# One-command init (venv + deps + db + migrate + seed)
make init-project

# Run
make run

# Run with docker
make run-docker

# Docker logs
make docker-logs

# Stop
make docker-down
```

### Windows

```bash
# create a virtual environment
python -m venv venv

# activate the virtual environment
venv\Scripts\activate

# install dependencies
pip install -r requirements.txt

# create database
python scripts/create_db.py

# migrate
flask db upgrade

# seed
flask seed-users

# run the app
flask run
```

### Docker

```bash
# Run with docker
docker compose up -d --build

# Docker logs
docker compose logs -f

# Stop
docker compose down

# Stop and remove volumes
docker compose down -v --remove-orphans
```


App runs at `http://localhost:5000`

---

## Environment Variables

Create a `.env` file in the project root:

---

## Project Structure

```
├── main.py                     # Entry point
├── config.py                   # Environment configuration
├── Makefile                    # Dev workflow commands
├── requirements.txt
├── vercel.json                 # Vercel deployment config
├── scripts/
│   └── create_db.py            # Auto-create PostgreSQL database
├── docs/
│   └── openapi.yaml            # OpenAPI 3.0 spec
├── app/
│   ├── __init__.py             # App factory
│   ├── cli.py                  # Flask CLI seeders
│   ├── extensions.py           # SQLAlchemy init
│   ├── models/
│   │   ├── user.py             # User (OAuth, roles)
│   │   ├── movie.py            # Movie (source: tmdb/user/admin)
│   │   ├── genre.py            # Genre
│   │   ├── movie_genre.py      # M2M junction table
│   │   ├── movie_image.py      # Poster & backdrop
│   │   ├── movie_video.py      # Cached trailers
│   │   ├── wishlist.py         # User wishlist
│   │   └── sync_log.py         # Sync history
│   ├── routes/
│   │   ├── auth_route.py       # /api/auth
│   │   ├── movie_route.py      # /api/movies
│   │   ├── wishlist_route.py   # /api/wishlists
│   │   ├── genre_route.py      # /api/genres
│   │   └── admin_route.py      # /api/admin
│   ├── services/               # Business logic layer
│   ├── schema/                 # Pydantic request/response schemas
│   └── helper/                 # Utilities (auth, jwt, logger, tmdb, pagination)
├── migrations/                 # Alembic migrations
└── tests/                      # Pytest suite
```

---

## API Endpoints

### 🔓 Public

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/movies` | List movies (search, filter, sort, paginate) |
| `GET` | `/api/movies/popular` | Popular movies |
| `GET` | `/api/movies/:id` | Movie detail + on-demand video fetch |
| `GET` | `/api/genres` | List genres |

### 🔐 Auth (`/api/auth`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/google/login` | Google OAuth login redirect |
| `GET` | `/google/callback` | OAuth callback |
| `POST` | `/refresh` | Refresh access token |
| `GET` | `/me` | Current user profile |
| `POST` | `/logout` | Logout |

### 👤 User Movies (`/api/movies`) — Requires Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/me` | List my movies |
| `POST` | `/user` | Create movie |
| `PUT` | `/user/:id` | Update own movie |
| `DELETE` | `/user/:id` | Soft-delete own movie |

### 📋 Wishlist (`/api/wishlists`) — Requires Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | List wishlist |
| `POST` | `/` | Add to wishlist |
| `PUT` | `/:id` | Update watch date |
| `DELETE` | `/:id` | Remove from wishlist |

### 🛡️ Admin (`/api/admin`) — Admin Only

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard` | Analytics dashboard |
| `GET` | `/movies` | List all movies (inc. archived) |
| `POST` | `/movies` | Create movie (admin fields) |
| `PUT` | `/movies/:id` | Update any movie |
| `DELETE` | `/movies/:id` | Delete any movie |
| `POST` | `/sync/movies` | Start TMDB sync |
| `GET` | `/sync/status` | Live sync progress |
| `GET` | `/sync/last-sync` | Last sync log |

> 📖 Full interactive docs: **http://localhost:5000/api/docs**

---

## TMDB Sync

Background sync with TMDB API. Two modes available:

```bash
# Full sync — all popular + now_playing movies
curl -X POST /api/admin/sync/movies \
  -H "Authorization: Bearer <token>"

# Incremental — only changed movies (last 14 days)
curl -X POST "/api/admin/sync/movies?mode=changes" \
  -H "Authorization: Bearer <token>"

# Resume from last failed position
curl -X POST "/api/admin/sync/movies?resume=true" \
  -H "Authorization: Bearer <token>"

# Check sync progress
curl /api/admin/sync/status -H "Authorization: Bearer <token>"
```

---

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make init-project` | Full setup (venv → deps → db → migrate → seed) |
| `make run` | Start dev server |
| `make shell` | Flask interactive shell |
| `make clean` | Remove `__pycache__` files |
| `make create-db` | Create PostgreSQL database |
| `make db-migrate MSG="..."` | Generate migration |
| `make db-upgrade` | Apply migrations |
| `make db-downgrade` | Rollback migration |
| `make db-history` | Migration history |
| `make db-seed` | Seed default users |
| `make test` | Run pytest |
| `make docker-up` | Start containers (build + up) |^
| `make docker-down` | Stop and remove containers |
| `make docker-logs` | Tail container logs |
| `make docker-clean` | Remove containers + volumes |

---

## Database Schema

```mermaid
erDiagram
    users ||--o{ movies : creates
    users ||--o{ wishlists : has
    movies ||--o{ movie_images : has
    movies ||--o{ movie_videos : has
    movies }o--o{ genres : categorized_by
    movies ||--o{ wishlists : in

    users {
        uuid id PK
        string name
        string email UK
        string role
        string oauth_provider
        string oauth_id
    }

    movies {
        uuid id PK
        string api_id UK
        string source
        string title
        text overview
        date release_date
        float popularity
        float rating
        uuid created_by FK
    }

    genres {
        uuid id PK
        string name UK
    }

    movie_images {
        uuid id PK
        uuid movie_id FK
        string image_type
        string image_url
    }

    movie_videos {
        uuid id PK
        uuid movie_id FK
        string video_type
        string site
        string video_key
    }

    wishlists {
        uuid id PK
        uuid user_id FK
        uuid movie_id FK
        date scheduled_watch_date
    }

    sync_logs {
        uuid id PK
        datetime last_sync_at
        int total_inserted
        int total_updated
        string status
        string error_message
    }
```

---

## Deployment

### Docker

```bash
# Start everything (PostgreSQL + Flask app)
docker compose up -d --build

# View logs
docker compose logs -f app

# Stop
docker compose down

# Stop + remove data
docker compose down -v
```

The app auto-runs migrations and seeds on startup.

### Vercel

```bash
vercel deploy
```

The project includes `vercel.json` configured for serverless deployment.

---

## License

This project is licensed under the [MIT License](LICENSE).
