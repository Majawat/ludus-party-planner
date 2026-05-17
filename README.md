# Ludus Party Planner

Self-hosted event registration for LAN parties and board game nights.

## Stack
Python, Flask, SQLite, DaisyUI, HTMX — runs in Docker.

## Setup (Docker)
1. Copy `.env.example` to `.env` and fill in values
2. `docker compose up --build`
3. Visit `/setup` to create the first admin and configure site settings

## Running in a GitHub Codespace

Docker is not required. Run the Flask dev server directly:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create a minimal .env (only SECRET_KEY is required to start)
cp .env.example .env
# Edit .env and set: SECRET_KEY=any-random-string

# 3. Create the database
flask db upgrade

# 4. (Optional) seed default site settings and a test event
flask seed-settings
flask seed-event

# 5. Start the dev server — 0.0.0.0 lets Codespaces forward the port
flask run --debug --host=0.0.0.0
```

Codespaces will detect port 5000 and offer a forwarded HTTPS URL.
Open that URL and visit `/setup` to create the first admin account.

> **Email**: transactional emails won't send without SMTP credentials in `.env`.
> The app works without them — verification links are logged to the terminal instead.

> **Passkeys**: WebAuthn requires the forwarded Codespace URL. In admin settings,
> set `WebAuthn RP ID` to the Codespace hostname (e.g. `abc123-5000.app.github.dev`)
> and `WebAuthn Origin` to the full HTTPS URL.

## Development
```bash
flask run --debug          # Dev server (port 5000)
python3 -m pytest          # Run test suite (402 tests)
flask seed-settings        # Seed site_settings defaults
flask seed-event           # Add a test LAN event
flask db migrate -m "msg"  # Generate a migration after model changes
flask db upgrade           # Apply pending migrations
```

See CLAUDE.md for the full project spec.
