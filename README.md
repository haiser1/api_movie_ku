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

- 🔐 **Authentication** — Login with Google OAuth2 or Email/Password, JWT access + refresh tokens
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
| `POST` | `/register` | Register new user with email and password |
| `POST` | `/email-password/login` | Login with email and password |
| `GET` | `/google/login` | Google OAuth login redirect |
| `GET` | `/google/callback` | OAuth callback |
| `POST` | `/refresh` | Refresh access token |
| `GET` | `/me` | Current user profile |
| `POST` | `/logout` | Logout |

### 👤 User Profile (`/api/users`) — Requires Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `PUT`  | `/me` | Update current user profile (name, picture) |
| `PUT`  | `/me/password` | Change user password |

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

The application synchronizes movie data from the TMDB API to keep the local database up to date. The sync process is designed to handle API rate limits and long-running tasks efficiently by utilizing a **frontend-driven batching mechanism**.

There are two primary synchronization modes:

### 1. Full Sync (`mode: "full"`)
Syncs a massive number of movies from popular endpoints (`/movie/popular`, `/movie/now_playing`, `/movie/top_rated`, `/movie/upcoming`). Because fetching thousands of movies in one request would cause timeouts, the sync is paginated:
- The frontend makes a request for page 1.
- The backend processes page 1 (~20 movies) and returns `status: "in_progress"` along with the `next_page` and `next_endpoint`.
- The frontend immediately makes the next request for the subsequent page/endpoint.
- This continues until the backend returns `status: "completed"`.

### 2. Changes Sync (`mode: "changes"`)
Syncs only movies that have changed in TMDB over the past 14 days. This is an incremental update designed to be fast and typically runs in a single synchronous call.

### Sync Flow Diagram

```mermaid
sequenceDiagram
    participant AdminUI as Admin Dashboard (Frontend)
    participant API as Backend API (Flask)
    participant DB as PostgreSQL DB
    participant TMDB as TMDB API

    AdminUI->>API: POST /api/admin/tmdb/sync/movies { "mode": "full" }
    activate API
    API->>TMDB: Fetch Genres (Initial Setup)
    TMDB-->>API: Genres list
    API->>DB: Update/Insert Genres
    API->>TMDB: Fetch Page 1 of first endpoint (e.g. /movie/popular)
    TMDB-->>API: 20 Movies
    API->>DB: Insert/Update 20 Movies + Create SyncLog
    API-->>AdminUI: 202 Accepted { status: "in_progress", next_page: 2, sync_log_id: "uuid" }
    deactivate API

    loop Frontend loops until completed
        AdminUI->>API: POST /api/admin/tmdb/sync/movies { mode: "full", page: 2, sync_log_id: "uuid" }
        activate API
        API->>TMDB: Fetch Page 2
        TMDB-->>API: 20 Movies
        API->>DB: Insert/Update 20 Movies + Update SyncLog
        API-->>AdminUI: 202 Accepted { status: "in_progress", next_page: 3 }
        deactivate API
    end

    Note over AdminUI, TMDB: Final Batch
    AdminUI->>API: POST /api/admin/tmdb/sync/movies { page: N, sync_log_id: "uuid" }
    activate API
    API->>TMDB: Fetch final page
    TMDB-->>API: Movies
    API->>DB: Insert/Update + Mark SyncLog "completed"
    API-->>AdminUI: 200 OK { status: "completed" }
    deactivate API

    Note over AdminUI, API: Admin can manually stop the sync
    AdminUI->>API: POST /api/admin/tmdb/sync/stop { sync_log_id: "uuid" }
    API->>DB: Mark SyncLog "stopped"
```

### API Usage Example

```bash
# First call (Full Sync)
curl -X POST http://localhost:5000/api/admin/tmdb/sync/movies \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"mode": "full", "max_pages": 50}'

# Subsequent call (driven by frontend)
curl -X POST http://localhost:5000/api/admin/tmdb/sync/movies \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "full", 
    "endpoint": "/movie/popular", 
    "page": 2, 
    "sync_log_id": "<uuid_from_first_response>"
  }'

# Stop an ongoing sync
curl -X POST http://localhost:5000/api/admin/tmdb/sync/stop \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"sync_log_id": "<uuid>"}'
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

link dbdiagram: https://dbdiagram.io/d/erd_movie_app-699c6b1fbd82f5fce289b078

![Entity Relationship Diagram](docs/erd_movie_app.png)

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

## Admin Account
```bash
Email: atmint@mail.com
Password: atmint123
```

----

## License

This project is licensed under the [MIT License](LICENSE).
