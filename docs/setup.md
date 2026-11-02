# Setup Guide

## Prerequisites

- Python 3.12+
- Bun (for frontend build)
- SQLite
  - PostgreSQL (optional, for production)

## Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone <repository-url>
cd blog-chat

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install Python dependencies
pdm install
```

### 2. Environment Variables

Create a `.env` file in the project root:

```bash
# Copy from example
cp example.env .env

# Edit .env with your values
DATABASE_URL=sqlite+aiosqlite:///chat.db
JWT_SECRET=your-secret-key-here
```

For production with PostgreSQL:

```bash
DATABASE_URL=postgresql+asyncpg://user:password@localhost/dbname
```

### 3. Content Directory

Ensure the `content/` directory exists with markdown files:

```bash
# Verify content directory exists
ls content/
```

### 4. Run Development Server

```bash
# Using PDM (recommended)
pdm dev

# Or using FastAPI directly
fastapi dev src/blog_chat/app.py
```

The app will be available at `http://localhost:8000`

### 5. Frontend Development (Optional)

For live-reload frontend development:

```bash
# Using Bun (recommended)
bun run watch

# Or using Vite directly
npx vite
```

## Available Commands

| Command                   | Description                             |
| ------------------------- | --------------------------------------- |
| `pdm dev`                 | Run development server                  |
| `pdm prod`                | Run production server on port 9091      |
| `pdm test`                | Run tests with coverage                 |
| `pdm watch`               | Watch mode for frontend                 |
| `pdm client_install`      | Install frontend dependencies           |
| `pdm client_watch`        | Watch mode for frontend (alias)         |
| `pdm build`               | Build frontend assets                   |
| `pdm migrate`             | Run database migrations                 |
| `pdm migration_create`    | Create new migration (requires message) |
| `pdm backup`              | Backup database to tarball              |
| `pdm clean`               | Clean pycache and build artifacts       |
| `pdm drop_db`             | Backup and delete database              |
| `pdm export_requirements` | Export requirements.txt for production  |

## Project Scripts (pyproject.toml)

```bash
# Build frontend
pdm build

# Watch mode
pdm watch

# Install client deps
pdm client_install
```

## Testing

```bash
# Run all tests
pdm test

# Or directly with pytest
pytest -v
```

## Building for Production

### 1. Build Frontend

```bash
pdm build
```

This outputs to `static/` directory.

### 2. Build Docker Container

```bash
docker build -t blog-chat .
docker run -p 9091:9091 blog-chat
```

### 3. Using Docker Compose

```bash
docker-compose up -d
```

## Production analytics (Umami)

Standard connection between this site and self-hosted Umami. Same procedure
for every property; only the website entry and env values differ.

**1. Umami side (dashboard, once per site).** Add a website (name `blog`,
URL `https://blog.chrislabs.net`) and copy its Website ID. Per website,
enable **Replays & Heatmaps**: sample rate `0.15`, mask `moderate`, block
`.chat-panel, .sensitive`, retention 30 days. Confirm the host answers:
`curl -I https://latitudem2m-analytics.chrislabs.net/script.js` and
`.../recorder.js` → `200` with a JavaScript content type.

**2. Server env.** This site reads analytics at runtime from `.env`
(no rebuild needed to rotate ID or host):

```bash
UMAMI_ENABLED="true"
UMAMI_SCRIPT_URL="https://latitudem2m-analytics.chrislabs.net/script.js"
UMAMI_RECORDER_URL="https://latitudem2m-analytics.chrislabs.net/recorder.js"
UMAMI_WEBSITE_ID="<blog-site-id>"
```

`compose.yaml` passes `.env` into the container (`env_file`), so
`mise deploy` picks it up. Empty ID or `UMAMI_ENABLED=false` renders no
`data-umami-*` attributes and the CSP omits the Umami origin (see
`docs/observability.md` § env table for the full reference).

**3. Verify.** After deploy: trigger a pageview + a chat message, then check
Umami Realtime (events appear under the blog entry), Replays (a sampled
session is listed), and the container logs (no CSP violations, no
`[umami]` send failures). With analytics disabled, view-source shows no
`data-umami-*` and no Umami host strings.

## Database

### SQLite (Development)

Default database is `chat.db` (SQLite). Created automatically on first run.

### PostgreSQL (Production)

Set `DATABASE_URL` to PostgreSQL connection string:

```
postgresql+asyncpg://username:password@localhost/databasename
```

## Project Structure Reference

```
blog-chat/
├── src/blog_chat/           # Python source code
│   ├── app.py              # FastAPI application
│   ├── core/               # Core utilities
│   │   ├── config.py       # Configuration
│   │   ├── database.py     # Database setup
│   │   └── responses.py    # Template rendering
│   └── features/           # Feature modules
│       ├── accounts/       # Authentication
│       ├── chat/           # Real-time chat
│       └── posts/          # Blog posts
├── static/                  # Built frontend assets
├── content/                 # Markdown blog posts
├── docs/                    # Documentation
├── tests/                   # Test suite
├── vite.config.js          # Vite build config
└── pyproject.toml          # Python project config
```

## Troubleshooting

### Database Errors

If you see database errors:

1. Check `DATABASE_URL` is set correctly
2. Ensure the database file/directory is writable
3. Try `pdm drop_db` to backup and recreate database

### Import Errors

If you see import errors:

1. Ensure you're in the virtual environment
2. Run `pdm install` again

### Frontend Not Loading

1. Run `pdm build` to generate static files
2. Check `static/` directory has files
3. Ensure `/static` mount point works in app

### WebSocket Connection Failed

1. Check browser console for errors
2. Ensure server is running
3. Verify WebSocket endpoint is accessible

## Development Workflow

1. Start backend: `pdm dev`
2. Start frontend watch: `pdm watch` (optional)
3. Make changes to code
4. Run tests: `pdm test`
5. Build frontend: `pdm build` (before commit)
