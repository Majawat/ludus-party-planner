# CLAUDE.md — Ludus Party Planner

This file is the single source of truth for the Ludus Party Planner project.
Read it fully before writing any code. Do not suggest alternatives to decisions
recorded here — they were made deliberately. If something is unclear, ask before
assuming.

---

## Project Overview

**Ludus Party Planner** is a self-hosted web application for managing board game
nights and LAN party events. It handles event creation, attendee registration,
ticket management, seat assignment, loaner equipment, potluck coordination, game
suggestions with voting, custom registration questions, Challonge tournament
integration, and online payment processing via Stripe and PayPal. The operator
runs approximately 2 events per year (one LAN party, one board game weekend) with
~30 attendees max, running the application on a home server behind a reverse proxy.
Every decision optimizes for **readability and maintainability over cleverness**.

---

## Non-Negotiable Constraints

- No frontend build process. No webpack, vite, npm for frontend assets.
- No frontend frameworks (React, Vue, Svelte). Server-rendered HTML only.
- All CSS and JS dependencies loaded from CDN.
- SQLite only. No PostgreSQL, no MySQL, no Redis.
- Everything runs in Docker via docker-compose.
- SSL and domain handled externally by a reverse proxy. Not in scope.
- The operator is the only admin initially. The system supports multiple admins
  via an `is_admin` flag on users.

---

## Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.12 | Readable, huge community, operator knows it |
| Framework | Flask 3.1.3 | Explicit, minimal magic, easy to understand |
| ORM | Flask-SQLAlchemy 3.1.1 | Standard, well documented |
| Migrations | Flask-Migrate 4.1.0 (Alembic) | Schema must evolve safely |
| Auth sessions | Flask-Login 0.6.3 | Handles session plumbing, well tested |
| Forms + CSRF | Flask-WTF 1.2.2 | CSRF protection is not optional |
| Email | Flask-Mail 0.10.0 | Simple SMTP wrapper |
| Password hashing | Werkzeug (built into Flask) | No extra install needed |
| Env vars | python-dotenv 1.2.2 | Reads .env file |
| CSS framework | DaisyUI (via CDN, on Tailwind Play CDN) | Theming system, no build step |
| Interactivity | HTMX (via CDN) | Dynamic interactions without writing JS |
| Production server | Gunicorn 23.0.0 | Replaces Flask dev server in Docker |
| Database | SQLite | Single file, fine at this scale |
| OAuth | Authlib 1.6.12 | Discord and Google login |
| Steam login | python3-openid>=3.2.0 | Steam uses OpenID 2.0, not OAuth 2.0 |
| Payments | stripe>=10.0.0 | Stripe Checkout Sessions |
| HTTP client | requests 2.33.0 | PayPal API, Challonge API, game lookups |
| Email validation | email-validator>=2.0 | WTForms Email validator dependency |
| Testing | pytest 9.0.3, pytest-flask 1.3.0 | Test suite |

All packages are pinned in `requirements.txt`.

### DaisyUI / Tailwind CDN Note
The Play CDN version of Tailwind is used (not production Tailwind). This is
acceptable for a low-traffic private site. The "not for production" label targets
high-traffic public sites. Do not suggest switching to a build step.

### HTMX Usage Pattern
Use HTMX for:
- Search boxes that filter results without page reload
- Inline check-in / mark-paid buttons in admin lists
- Schedule items and question rows added via HTMX partial responses
- Any action where a full page reload would feel jarring

Do NOT use HTMX for everything. Standard form POST + redirect is fine for most
actions and easier to reason about. When in doubt, use a standard form.

---

## Project Structure

```
ludus/
├── app.py                  # App factory (create_app), config, extension init, CLI commands
├── models.py               # ALL SQLAlchemy models in one file; slugify, unique_slug helpers
├── forms.py                # ALL WTForms form classes in one file
├── mailer.py               # Email sending helper functions (named mailer.py to avoid stdlib conflict)
├── extensions.py           # csrf (CSRFProtect) and oauth (OAuth) singletons
├── challonge.py            # Challonge API client (requests-based)
├── game_lookup.py          # BGG XML API and Steam store API search/detail functions
├── payments.py             # Stripe and PayPal integration helpers
├── activity.py             # Admin action logging helper (log function only)
│
├── routes/
│   ├── __init__.py         # register_blueprints(app) — registers all five blueprints
│   ├── setup.py            # Blueprint: /setup (first-run onboarding wizard)
│   ├── public.py           # Blueprint: /, /events, game suggestions, game search
│   ├── auth.py             # Blueprint: /register, /login, OAuth, Steam OpenID
│   ├── account.py          # Blueprint: /dashboard, /account, registration, seats,
│   │                       #            payments (Stripe/PayPal), webhooks, tournaments
│   └── admin.py            # Blueprint: all /admin/* routes
│
├── templates/
│   ├── base.html           # Master layout (loads DaisyUI, HTMX, nav, footer)
│   ├── errors/
│   │   ├── 403.html
│   │   ├── 404.html
│   │   └── 500.html
│   ├── setup/
│   │   ├── step1.html
│   │   ├── step2.html
│   │   └── complete.html
│   ├── public/
│   │   ├── index.html
│   │   ├── events.html
│   │   ├── event_detail.html
│   │   └── game_search_results.html   # HTMX partial for game search
│   ├── auth/
│   │   ├── login.html
│   │   ├── register.html
│   │   ├── forgot_password.html
│   │   ├── reset_password.html
│   │   ├── oauth_confirm_link.html
│   │   ├── steam_complete_registration.html
│   │   └── 2fa_verify.html            # 2FA challenge on login
│   ├── account/
│   │   ├── dashboard.html
│   │   ├── profile.html
│   │   ├── security.html              # 2FA management page
│   │   ├── security_setup.html        # 2FA QR code + verify
│   │   ├── backup_codes_display.html  # Show backup codes once
│   │   ├── register_event.html
│   │   ├── my_registration.html
│   │   ├── seats.html
│   │   └── seats_grid_partial.html    # HTMX partial for seat grid
│   └── admin/
│       ├── dashboard.html
│       ├── settings.html
│       ├── email.html
│       ├── equipment.html
│       ├── logs.html                  # Activity log
│       ├── events/
│       │   ├── list.html
│       │   ├── detail.html
│       │   ├── edit.html
│       │   ├── tickets.html
│       │   ├── ticket_edit.html
│       │   ├── schedule.html
│       │   ├── seats.html
│       │   ├── loaners.html
│       │   ├── checkin.html
│       │   ├── questions.html
│       │   ├── question_edit.html
│       │   ├── _status_badge.html     # HTMX partial
│       │   ├── _schedule_row.html     # HTMX partial
│       │   ├── _checkin_rows.html     # HTMX partial
│       │   ├── _checkin_row.html      # HTMX partial
│       │   ├── _question_row.html     # HTMX partial
│       │   ├── registrations/
│       │   │   ├── list.html
│       │   │   ├── detail.html
│       │   │   └── _rows.html         # HTMX partial
│       │   └── tournaments/
│       │       ├── list.html
│       │       ├── new.html
│       │       ├── detail.html
│       │       ├── add_participants.html
│       │       ├── matches.html
│       │       └── _match_row.html    # HTMX partial
│       └── users/
│           ├── list.html
│           ├── detail.html
│           └── _rows.html             # HTMX partial
│
├── static/
│   ├── css/
│   │   └── ludus.css       # Minimal overrides only. Avoid writing CSS.
│   └── js/
│       └── seats.js        # Seat selection UI
│
├── data/
│   └── ludus.db            # SQLite file — gitignored
│
├── migrations/             # Auto-generated by Flask-Migrate. Do not edit manually.
│   └── env.py              # Contains render_as_batch=True for SQLite ALTER support
│
├── tests/
│   ├── conftest.py         # Fixtures: app, client, users, events, tickets, seat, registration
│   ├── test_admin.py       # Admin routes, mark paid/comped, check-in, seat assignment
│   ├── test_auth.py        # Registration, login, verification, password reset
│   ├── test_events.py      # Registration rules, capacity, guards, cancellation
│   ├── test_events_public.py  # Public event listing, event detail page
│   ├── test_game_lookup.py # BGG/Steam search and detail functions + /games/search route
│   ├── test_oauth.py       # Discord/Google OAuth login and account linking
│   ├── test_payments.py    # Stripe and PayPal checkout flows and webhooks
│   ├── test_setup.py       # First-run wizard, setup guard redirect
│   ├── test_steam.py       # Steam OpenID login, account linking, disconnect
│   ├── test_v11.py         # Schedule, potluck, loaner equipment, announcements, check-in mode
│   ├── test_v12.py         # Game suggestions + voting, visual seat map/claim/release
│   ├── test_v13.py         # Challonge tournament CRUD, participants, matches, reporting
│   ├── test_v14.py         # v1.3 remaining: activity logging, location link, UI tests
│   ├── test_passkeys.py    # WebAuthn passkey registration, login, removal
│   └── test_2fa.py         # TOTP 2FA: login flow, setup, disable, backup codes
│
├── .env                    # Secrets — gitignored
├── .env.example            # Template committed to repo
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Helper Modules

### mailer.py
Sends all transactional and mass email via Flask-Mail. Named `mailer.py` (not
`email.py`) because `email` is a Python standard library module — importing
`from email import ...` would shadow it. Functions: `send_verification_email`,
`send_password_reset_email`, `send_registration_confirmation_email`,
`send_registration_pending_payment_email` (sent when a Stripe or PayPal checkout
is initiated but not yet completed), and `send_mass_email` (used by the admin mass
email composer). All functions import `mail` from `app` inside the function body to
avoid circular imports. `_apply_mail_settings()` is a module-level helper called at
the start of every send function — it reads the six `mail_*` keys from SiteSettings
and updates `app.config` so Flask-Mail always uses the current settings. If
`mail_server` is empty, `MAIL_SUPPRESS_SEND` is set to `True` automatically so a
fresh install degrades gracefully without connection errors.

### challonge.py
Thin wrapper around the Challonge REST API v1 (`api.challonge.com/v1`). All
requests are authenticated with `api_key` as a query parameter, read from
`SiteSettings`. Functions: `create_tournament`, `add_participants_bulk`,
`remove_participant`, `start_tournament`, `reset_tournament`, `get_tournament`,
`get_participants`, `get_open_matches`, `report_match`, `delete_tournament`, and
`generate_url_slug`. Every function raises `requests.RequestException` on HTTP
errors — callers must catch it and degrade gracefully. The `_api` helper calls
`resp.raise_for_status()` before returning. Use this module whenever you need to
talk to Challonge; never call the Challonge API directly from routes.

### game_lookup.py
Provides game search and detail lookup for BoardGameGeek and Steam. `search_bgg`
and `search_steam` return a list of lightweight result dicts (`{id, name, year,
source, image}`). `get_bgg_game` fetches full details from the BGG XML API 2
(parsed with `xml.etree.ElementTree`); it handles BGG's HTTP 202 "queued" response
by sleeping 2 seconds and retrying once. `get_steam_game` fetches details from the
Steam store `appdetails` endpoint. `search_games` is the safe wrapper used by
routes — it calls `search_bgg` and/or `search_steam`, silently catching all
exceptions, and returns `[]` on error or if the query is shorter than 2 characters.
The lower-level functions (`search_bgg`, `get_bgg_game`, `search_steam`,
`get_steam_game`) raise on error; callers should use `search_games` or wrap in
try/except.

### payments.py
Encapsulates all Stripe and PayPal logic. For Stripe: `create_stripe_session`
creates a server-side Checkout Session (no Stripe.js required) and returns
`(session_id, checkout_url)`; `retrieve_stripe_session` returns the Session object
or `None` on error. For PayPal: `create_paypal_order` uses Orders API v2 via
`requests` and returns `(order_id, approve_url)`; `capture_paypal_order` captures
an approved order and returns `True`/`False`; `verify_paypal_webhook` verifies
webhook signatures via the PayPal webhook verification endpoint. All credentials
are read from `SiteSettings` at call time. Stripe and PayPal can be independently
enabled/disabled via `stripe_enabled` and `paypal_enabled` site settings.

### activity.py
Single helper function used by admin routes to record write actions.
`log(action, target_type=None, target_id=None, details=None)` reads
`current_user` from Flask-Login context to populate `user_id`, captures
`request.remote_addr` for `ip_address`, and inserts an `ActivityLog` row.
`details` is a dict that the function serializes to JSON before storing.
Only the curated list of admin write actions defined in the roadmap is logged —
not every database write. Import and call `log(...)` at the end of each listed
admin route handler, after the DB commit.

---

## Database Schema

All models live in `models.py`. Migrations are managed by Flask-Migrate.
Never modify the database schema directly — always use migrations.

Fields marked [post-v1.0] were added after the initial v1.0 release.

---

### users
```
id                  INTEGER PK
first_name          TEXT NOT NULL
last_name           TEXT NOT NULL
gamertag            TEXT NULLABLE
email               TEXT NOT NULL UNIQUE
password_hash       TEXT NULLABLE            -- NULL for OAuth-only users
is_admin            BOOLEAN DEFAULT FALSE NOT NULL
newsletter_opt_in   BOOLEAN DEFAULT FALSE NOT NULL
avatar_url          TEXT NULLABLE
email_verified_at   DATETIME NULLABLE        -- NULL = unverified
preferred_theme     TEXT NULLABLE            -- user-selected theme; NULL = use site default
totp_secret         TEXT NULLABLE            -- base32 secret; NULL = 2FA disabled
totp_backup_codes   TEXT NULLABLE            -- JSON array of hashed single-use codes
created_at          DATETIME DEFAULT NOW NOT NULL
updated_at          DATETIME DEFAULT NOW NOT NULL
```
Migration: splits existing `name` column on first space into `first_name` and `last_name`.

Relationships: `platform_accounts` (UserPlatformAccount, back_populates),
`registrations` (backref), `verification_tokens` (backref), `reset_tokens`
(backref), `announcements` (backref), `game_suggestions` (backref),
`suggestion_votes` (backref).

Methods: `set_password`, `check_password`, `has_password` (property),
`is_verified` (property), `name` (@property returning
`f"{self.first_name} {self.last_name}"` for backwards compatibility in admin
contexts).

---

### email_verification_tokens
```
id                  INTEGER PK
user_id             INTEGER FK -> users NOT NULL
token_hash          TEXT NOT NULL
expires_at          DATETIME NOT NULL        -- 48 hours from creation
```
Class method `create_for_user(user)` generates a raw token, stores its SHA-256
hash, and returns the raw token to be emailed.

---

### password_reset_tokens
```
id                  INTEGER PK
user_id             INTEGER FK -> users NOT NULL
token_hash          TEXT NOT NULL
expires_at          DATETIME NOT NULL        -- 1 hour from creation
used_at             DATETIME NULLABLE        -- NULL = still valid
```
`is_valid` property: `used_at is None and expires_at > utcnow()`.

---

### user_platform_accounts
```
id                  INTEGER PK
user_id             INTEGER FK -> users NOT NULL
platform            TEXT NOT NULL
                    -- valid values: 'steam', 'discord', 'google', 'epic',
                    -- 'xbox', 'psn', 'battlenet', 'boardgamegeek'
username            TEXT NOT NULL
platform_user_id    TEXT NULLABLE

UNIQUE(user_id, platform)
UNIQUE(platform, platform_user_id)
```

---

### site_settings
```
key                 TEXT PK
value               TEXT NOT NULL
```

Default rows seeded by `flask seed-settings`:
```
site_name                        = "Ludus Party Planner"
site_tagline                     = "Board Games & LAN Parties"
contact_email                    = ""
logo_url                         = ""
favicon_url                      = ""
discord_url                      = ""
twitch_url                       = ""
youtube_url                      = ""
instagram_url                    = ""
facebook_url                     = ""
terms_of_service                 = ""
privacy_policy                   = ""
registration_enabled             = "true"
show_upcoming_event_on_homepage  = "true"
venmo_handle                     = ""
ui_theme                         = "dark"
discord_oauth_client_id          = ""
discord_oauth_client_secret      = ""
google_oauth_client_id           = ""
google_oauth_client_secret       = ""
steam_enabled                    = "false"
steam_api_key                    = ""
stripe_enabled                   = "false"
stripe_publishable_key           = ""
stripe_secret_key                = ""
stripe_webhook_secret            = ""
paypal_enabled                   = "false"
paypal_client_id                 = ""
paypal_client_secret             = ""
paypal_mode                      = "sandbox"
paypal_webhook_id                = ""
challonge_api_key                = ""
challonge_username               = ""
itad_api_key                     = ""
passkeys_enabled                 = "false"
webauthn_rp_id                   = ""   -- e.g. "yourlan.party"; required behind a reverse proxy
webauthn_origin                  = ""   -- e.g. "https://yourlan.party"; required behind a reverse proxy
mail_server                      = ""
mail_port                        = "587"
mail_use_tls                     = "true"   (boolean, handled by _BOOL_SETTINGS)
mail_username                    = ""
mail_password                    = ""       (stored plain, protected by server security)
mail_default_sender              = ""
```

The first-run wizard also writes `setup_complete = "true"` when onboarding is done.
`base.html` reads `ui_theme` from the context processor. Admin pages always render
with `data-theme="dim"`.

---

### events
```
id                  INTEGER PK
name                TEXT NOT NULL
slug                TEXT NOT NULL UNIQUE
type                TEXT NOT NULL            -- 'lan' or 'board_game'
status              TEXT NOT NULL DEFAULT 'draft'
                    -- 'draft', 'published', 'archived'
description         TEXT NULLABLE            -- Full Markdown description
short_description   TEXT NULLABLE            -- One-liner for listing cards (Markdown supported)
start_datetime      DATETIME NOT NULL
end_datetime        DATETIME NOT NULL
location            TEXT NOT NULL
                    -- supports GPS coordinates in 'lat,lng' format
                    -- (e.g. 38.8976,-77.0366) for venues without a street address.
                    -- The event detail page wraps location in a Google Maps link:
                    -- https://www.google.com/maps?q=<urlencode(location)>
cover_image_url     TEXT NULLABLE
gallery_url         TEXT NULLABLE
                    -- Link to a Google Photos shared album. If set, the event
                    -- detail page shows a "View Photos" link. Users can join the
                    -- album from within Google Photos. No iframe embed (blocked by
                    -- X-Frame-Options). No separate join URL field.
location_map_embed_url TEXT NULLABLE         -- [planned-v1.3] iframe src from
                    -- Google Maps → Share → Embed a map. Admin pastes only the
                    -- src URL, not the full <iframe> HTML. Template constructs
                    -- the iframe. If not set, no map is shown.
seating_enabled     BOOLEAN DEFAULT FALSE NOT NULL
registration_open   BOOLEAN DEFAULT TRUE NOT NULL
registration_closes_at DATETIME NULLABLE
collect_emergency_contacts BOOLEAN DEFAULT FALSE NOT NULL
                    -- when True, emergency contact fields appear on registration form
                    -- regardless of ticket type lodging status
created_at          DATETIME DEFAULT NOW NOT NULL
updated_at          DATETIME DEFAULT NOW NOT NULL
```
Relationships: `ticket_types` (ordered by id, cascade delete-orphan),
`registrations` (ordered by created_at), `schedule_items` (ordered by starts_at,
cascade delete-orphan), `potluck_items` (cascade delete-orphan), `announcements`
(ordered by created_at, cascade delete-orphan), `game_suggestions` (cascade
delete-orphan), `questions` (ordered by display_order, cascade delete-orphan),
`tournaments` (cascade delete-orphan), `seats` (backref).

Properties: `capacity` (sum of active ticket_type.quantity_total),
`is_upcoming` (start_datetime > utcnow()), `type_label` ("LAN Party" / "Board Game Night").

---

### ticket_types
```
id                  INTEGER PK
event_id            INTEGER FK -> events NOT NULL
name                TEXT NOT NULL
description         TEXT NULLABLE
price               DECIMAL(10,2) DEFAULT 0.00 NOT NULL
quantity_total      INTEGER NOT NULL
seatable            BOOLEAN DEFAULT FALSE NOT NULL
includes_lodging    BOOLEAN DEFAULT FALSE NOT NULL
valid_days          TEXT NOT NULL            -- JSON array of ISO date strings
max_per_user        INTEGER DEFAULT 1 NOT NULL
is_active           BOOLEAN DEFAULT TRUE NOT NULL
created_at          DATETIME DEFAULT NOW NOT NULL
```
`quantity_sold` property: counts non-cancelled registrations for this ticket type.
`valid_days_list` property: parses the JSON array.

Do not allow editing `price`, `quantity_total`, or `seatable` on a ticket type
that has active registrations without a prominent warning in the UI.

---

### seats
```
id                  INTEGER PK
event_id            INTEGER FK -> events NOT NULL
label               TEXT NOT NULL
display_order       INTEGER DEFAULT 0 NOT NULL
```

---

### registrations
```
id                      INTEGER PK
user_id                 INTEGER FK -> users NOT NULL
event_id                INTEGER FK -> events NOT NULL
ticket_type_id          INTEGER FK -> ticket_types NOT NULL
seat_id                 INTEGER FK -> seats NULLABLE
status                  TEXT DEFAULT 'pending' NOT NULL
                        -- 'pending', 'confirmed', 'cancelled'
payment_status          TEXT DEFAULT 'unpaid' NOT NULL
                        -- 'unpaid', 'paid', 'comped'
payment_method          TEXT NULLABLE        -- 'cash', 'venmo', 'paypal', 'stripe', 'other'
paid_at                 DATETIME NULLABLE
checked_in_at           DATETIME NULLABLE
checkin_code            TEXT NOT NULL UNIQUE -- UUID generated at registration
needs_loaner            BOOLEAN DEFAULT FALSE NOT NULL
emergency_contact_name  TEXT NULLABLE
emergency_contact_phone TEXT NULLABLE
terms_accepted_at       DATETIME NULLABLE
admin_notes             TEXT NULLABLE
stripe_session_id       TEXT NULLABLE        -- [post-v1.0]
paypal_order_id         TEXT NULLABLE        -- [post-v1.0]
payment_processor       TEXT NULLABLE        -- 'stripe', 'paypal', 'manual' [post-v1.0]
created_at              DATETIME DEFAULT NOW NOT NULL
updated_at              DATETIME DEFAULT NOW NOT NULL

UNIQUE(user_id, event_id)
```
Relationships: `user`, `event`, `ticket_type`, `seat`, `answers` (cascade
delete-orphan), `loaner_requests` (dynamic backref), `potluck_items` (backref),
`tournament_participations` (backref).

`status` and `payment_status` are intentionally separate. A registration can be
`confirmed` + `unpaid` or `confirmed` + `comped`.

---

### event_schedule_items
```
id                  INTEGER PK
event_id            INTEGER FK -> events NOT NULL
title               TEXT NOT NULL
description         TEXT NULLABLE
starts_at           DATETIME NOT NULL
ends_at             DATETIME NULLABLE
display_order       INTEGER DEFAULT 0 NOT NULL
```

---

### potluck_items
```
id                  INTEGER PK
event_id            INTEGER FK -> events NOT NULL
registration_id     INTEGER FK -> registrations NOT NULL
description         TEXT NOT NULL
event_date          DATE NULLABLE            -- which day of multi-day event; NULL = single-day
created_at          DATETIME DEFAULT NOW NOT NULL
updated_at          DATETIME DEFAULT NOW NOT NULL
```

---

### loaner_equipment
```
id                  INTEGER PK
name                TEXT NOT NULL
description         TEXT NULLABLE
specs               TEXT NULLABLE
is_available        BOOLEAN DEFAULT TRUE NOT NULL
created_at          DATETIME DEFAULT NOW NOT NULL
```

---

### loaner_requests
```
id                  INTEGER PK
registration_id     INTEGER FK -> registrations NOT NULL
equipment_id        INTEGER FK -> loaner_equipment NULLABLE
status              TEXT DEFAULT 'requested' NOT NULL
                    -- 'requested', 'approved', 'denied'
notes               TEXT NULLABLE
created_at          DATETIME DEFAULT NOW NOT NULL
```

---

### event_announcements
```
id                  INTEGER PK
event_id            INTEGER FK -> events NOT NULL
title               TEXT NOT NULL
body                TEXT NOT NULL
created_by          INTEGER FK -> users NOT NULL
created_at          DATETIME DEFAULT NOW NOT NULL
```

---

### game_suggestions
```
id                  INTEGER PK
event_id            INTEGER FK -> events NOT NULL
suggested_by        INTEGER FK -> users NOT NULL
game_name           TEXT NOT NULL
bgg_id              INTEGER NULLABLE
steam_app_id        INTEGER NULLABLE
game_image_url      TEXT NULLABLE            -- [post-v1.0] enriched from BGG/Steam
game_description    TEXT NULLABLE            -- [post-v1.0]
game_year           INTEGER NULLABLE         -- [post-v1.0]
game_min_players    INTEGER NULLABLE         -- [post-v1.0]
game_max_players    INTEGER NULLABLE         -- [post-v1.0]
play_style          TEXT NULLABLE            -- 'co-op', 'competitive', 'both'
system_requirements TEXT NULLABLE            -- freetext e.g. "Low", "Medium/High", "Requires controller"
notes               TEXT NULLABLE            -- context from the suggester
suggested_datetime  DATETIME NULLABLE
created_at          DATETIME DEFAULT NOW NOT NULL
```
Relationships: `event`, `suggester`, `votes` (cascade delete-orphan).

---

### game_suggestion_votes
```
id                  INTEGER PK
suggestion_id       INTEGER FK -> game_suggestions NOT NULL
user_id             INTEGER FK -> users NOT NULL
created_at          DATETIME DEFAULT NOW NOT NULL

UNIQUE(suggestion_id, user_id)
```

---

### event_questions
```
id                  INTEGER PK
event_id            INTEGER FK -> events NOT NULL
question_text       TEXT NOT NULL
question_type       TEXT DEFAULT 'text' NOT NULL
                    -- 'text', 'boolean', 'select'
field_name          TEXT NOT NULL            -- slugified, unique per event
is_required         BOOLEAN DEFAULT FALSE NOT NULL
display_order       INTEGER DEFAULT 0 NOT NULL
options             TEXT NULLABLE            -- JSON array, only for 'select' type

UNIQUE(event_id, field_name)
```
`options_list` property parses the JSON. `field_name` is generated by
`unique_field_name()` in models.py.

---

### registration_answers
```
id                  INTEGER PK
registration_id     INTEGER FK -> registrations NOT NULL
question_id         INTEGER FK -> event_questions NOT NULL
answer              TEXT NULLABLE

UNIQUE(registration_id, question_id)
```

---

### tournaments
```
id                  INTEGER PK
event_id            INTEGER FK -> events NOT NULL
name                TEXT NOT NULL
game_name           TEXT NOT NULL
format              TEXT DEFAULT 'single elimination' NOT NULL
                    -- 'single elimination', 'double elimination',
                    -- 'round robin', 'swiss'
description         TEXT NULLABLE
challonge_id        INTEGER NULLABLE
challonge_url_slug  TEXT NULLABLE
challonge_full_url  TEXT NULLABLE
status              TEXT DEFAULT 'pending' NOT NULL
                    -- 'pending', 'underway', 'complete'
sign_ups_open       BOOLEAN DEFAULT TRUE NOT NULL
created_at          DATETIME DEFAULT NOW NOT NULL
```
Relationships: `event`, `participants` (cascade delete-orphan).

---

### tournament_participants
```
id                          INTEGER PK
tournament_id               INTEGER FK -> tournaments NOT NULL
registration_id             INTEGER FK -> registrations NULLABLE
challonge_participant_id    INTEGER NULLABLE
display_name                TEXT NOT NULL
seed                        INTEGER NULLABLE
created_at                  DATETIME DEFAULT NOW NOT NULL
```
`registration_id` is NULL for manually-added participants (non-attendees).

---

### webauthn_credentials
```
id              INTEGER PK
user_id         INTEGER FK -> users NOT NULL
credential_id   TEXT NOT NULL UNIQUE     -- base64url-encoded bytes
public_key      TEXT NOT NULL            -- base64url-encoded bytes
sign_count      INTEGER NOT NULL DEFAULT 0
device_name     TEXT NULLABLE            -- user-supplied label (e.g. "YubiKey")
aaguid          TEXT NULLABLE
created_at      DATETIME NOT NULL
last_used_at    DATETIME NULLABLE
```

---

### activity_log
```
id          INTEGER PK
user_id     INTEGER FK -> users NULLABLE  -- NULL = system action
action      TEXT NOT NULL
            -- Convention: "resource.verb"
            -- e.g. "registration.marked_paid", "event.created",
            --      "user.admin_granted", "tournament.started"
target_type TEXT NOT NULL                 -- e.g. "registration", "event", "user"
target_id   INTEGER NULLABLE
details     TEXT NULLABLE                 -- JSON string with relevant context
            -- e.g. {"from": "unpaid", "to": "paid", "method": "cash"}
ip_address  TEXT NULLABLE
created_at  DATETIME NOT NULL
```
Append-only. No update or delete routes for log entries. Populated exclusively
via `activity.log()` — never written directly from routes.

Logged actions (and only these):
`registration.marked_paid`, `registration.marked_comped`,
`registration.checked_in`, `registration.cancelled`,
`registration.seat_assigned`, `registration.admin_notes_updated`,
`event.created`, `event.updated`, `event.status_changed`, `event.deleted`,
`ticket_type.created`, `ticket_type.updated`,
`user.admin_granted`, `user.admin_revoked`,
`tournament.started`, `tournament.reset`, `tournament.deleted`,
`equipment.approved`, `equipment.denied`

---

## URL Map

### Health check (app.py)
```
GET  /ping                          JSON health check {"status": "ok"}
```

### Setup blueprint (routes/setup.py)
```
GET  POST  /setup                   Step 1: create first admin account
GET  POST  /setup/site              Step 2: site name, tagline, theme
GET        /setup/complete          Show completion page (read-only; setup_complete is written by step2 POST)
```

### Public blueprint (routes/public.py)
```
GET        /                             Homepage — next upcoming published event
GET        /events                       All published events
GET        /events/<slug>                Event detail: attendees, schedule, potluck,
                                         announcements, game suggestions
POST       /events/<slug>/suggestions/add              Add game suggestion (login required)
POST       /events/<slug>/suggestions/<sid>/vote       Toggle vote on suggestion (login required)
GET        /games/search                 HTMX-only game search (BGG+Steam, login required)
```

### Auth blueprint (routes/auth.py)
```
GET  POST  /register                            Account creation (with honeypot)
GET  POST  /login                               Login form
GET        /logout                              Logout (login required)
GET        /verify-email/<token>                Complete email verification
POST       /resend-verification                 Resend verification email (login required)
GET  POST  /forgot-password                     Password reset request
GET  POST  /reset-password/<token>              Password reset form
GET        /auth/<provider>/login               OAuth login redirect (discord, google)
GET        /auth/<provider>/callback            OAuth callback
POST       /auth/<provider>/confirm-link        Confirm linking OAuth to existing account
GET        /auth/steam/login                    Steam OpenID redirect
GET        /auth/steam/callback                 Steam OpenID callback
GET  POST  /auth/steam/complete-registration    New user via Steam (collect email/password)
GET  POST  /auth/2fa/verify                     2FA challenge during login
```

### Account blueprint (routes/account.py)
```
GET        /dashboard                                My registrations (login required)
GET        /account                                  Profile + connected accounts (login required)
POST       /account/set-password                     Set password for OAuth-only users (login required)
POST       /account/change-password                  Change existing password (login required)
POST       /account/connect/<provider>               Connect Discord/Google (login required)
POST       /account/disconnect/<provider>            Disconnect Discord/Google (login required)
POST       /account/connect/steam                    Connect Steam (login required)
POST       /account/disconnect/steam                 Disconnect Steam (login required)
GET  POST  /events/<slug>/register                   Event registration form (login required)
GET        /events/<slug>/my-registration            My registration detail (login required)
POST       /events/<slug>/my-registration/answers    Update custom question answers (login required)
POST       /events/<slug>/my-registration/cancel     Cancel registration (login required)
POST       /events/<slug>/my-registration/loaner     Add/remove loaner request (login required)
POST       /events/<slug>/my-registration/potluck/add              Add potluck item (login required)
POST       /events/<slug>/my-registration/potluck/<item_id>/delete Remove potluck item (login required)
GET        /events/<slug>/seats                      Seat selection page (login required)
POST       /events/<slug>/seats/claim                Claim a seat (login required, HTMX-aware)
POST       /events/<slug>/seats/release              Release seat (login required, HTMX-aware)
GET        /account/stripe/success                   Stripe post-checkout return (login required)
GET        /account/paypal/success                   PayPal post-checkout return (login required)
POST       /account/stripe/webhook                   Stripe webhook (CSRF exempt)
POST       /account/paypal/webhook                   PayPal webhook (CSRF exempt)
POST       /events/<slug>/tournaments/<tid>/signup   Sign up for tournament (login required)
POST       /events/<slug>/tournaments/<tid>/withdraw Withdraw from tournament (login required)
GET        /account/security                        2FA management page (login required)
GET        /account/security/setup                  Show QR code for 2FA setup (login required)
POST       /account/security/verify-setup           Verify TOTP code, save secret to DB (login required)
GET        /account/security/backup-codes-display   Show backup codes once (login required)
POST       /account/security/disable                Disable 2FA, requires password (login required)
POST       /account/security/regenerate-backup-codes  Regenerate backup codes, requires password (login required)
```

### Admin blueprint (routes/admin.py — all routes require is_admin=True)
```
GET        /admin/                          Admin dashboard (event + user counts)
GET  POST  /admin/settings                 Site settings (all keys from site_settings table)

GET        /admin/events                   All events list
GET  POST  /admin/events/new              Create event
GET        /admin/events/<id>             Event management hub
GET  POST  /admin/events/<id>/edit        Edit event
POST       /admin/events/<id>/clone       Clone event with ticket types
POST       /admin/events/<id>/toggle-status  HTMX status badge swap

GET        /admin/events/<id>/tickets                  Ticket types list
GET  POST  /admin/events/<id>/tickets/new             Create ticket type
GET  POST  /admin/events/<id>/tickets/<tid>/edit      Edit ticket type

GET        /admin/events/<id>/registrations              List (filterable, HTMX-searchable)
GET        /admin/events/<id>/registrations/export.csv  CSV export (includes custom Q answers)
GET        /admin/events/<id>/registrations/<rid>        Registration detail
POST       /admin/events/<id>/registrations/<rid>/mark-paid      Mark paid
POST       /admin/events/<id>/registrations/<rid>/mark-comped    Mark comped
POST       /admin/events/<id>/registrations/<rid>/check-in       Check in (HTMX-aware)
POST       /admin/events/<id>/registrations/<rid>/undo-checkin   Undo check-in
POST       /admin/events/<id>/registrations/<rid>/cancel         Cancel registration
POST       /admin/events/<id>/registrations/<rid>/notes          Save admin notes
POST       /admin/events/<id>/registrations/<rid>/assign-seat    Admin reassign seat

GET        /admin/events/<id>/seats                Seat management (list, add, bulk add)
POST       /admin/events/<id>/seats/add            Add single seat
POST       /admin/events/<id>/seats/bulk-add       Bulk add seats
POST       /admin/events/<id>/seats/<sid>/delete   Delete seat (blocked if claimed)

GET        /admin/events/<id>/schedule                    Schedule list + add form
POST       /admin/events/<id>/schedule/add                Add schedule item (HTMX-aware)
POST       /admin/events/<id>/schedule/<item_id>/delete   Delete schedule item (HTMX-aware)

POST       /admin/events/<id>/announcements/add               Post announcement
POST       /admin/events/<id>/announcements/<ann_id>/delete   Delete announcement

GET        /admin/equipment                         Loaner equipment list + add form
POST       /admin/equipment/add                     Add equipment
POST       /admin/equipment/<eid>/edit              Edit equipment
POST       /admin/equipment/<eid>/toggle            Toggle availability

GET        /admin/events/<id>/loaners                    Loaner requests for event
POST       /admin/events/<id>/loaners/<req_id>/approve   Approve loaner request
POST       /admin/events/<id>/loaners/<req_id>/deny      Deny loaner request

GET        /admin/events/<id>/checkin                Check-in mode (tablet-friendly)
GET        /admin/events/<id>/checkin/search         HTMX-only attendee search for check-in

GET        /admin/events/<id>/questions                    Custom questions list + add form
POST       /admin/events/<id>/questions/add                Add question (HTMX-aware)
GET  POST  /admin/events/<id>/questions/<qid>/edit         Edit question
POST       /admin/events/<id>/questions/<qid>/delete       Delete question (blocked if answers exist)

GET        /admin/events/<id>/tournaments                                  Tournament list
GET  POST  /admin/events/<id>/tournaments/new                              Create tournament
GET        /admin/events/<id>/tournaments/<tid>                            Tournament detail
GET  POST  /admin/events/<id>/tournaments/<tid>/add-participants           Add attendees as participants
POST       /admin/events/<id>/tournaments/<tid>/add-manual                 Add manual participant
POST       /admin/events/<id>/tournaments/<tid>/remove-participant/<pid>   Remove participant
POST       /admin/events/<id>/tournaments/<tid>/start                      Start tournament on Challonge
POST       /admin/events/<id>/tournaments/<tid>/reset                      Reset tournament
GET        /admin/events/<id>/tournaments/<tid>/matches                    Open matches view
POST       /admin/events/<id>/tournaments/<tid>/matches/<match_id>/report  Report match result (HTMX-aware)
POST       /admin/events/<id>/tournaments/<tid>/delete                     Delete tournament

GET        /admin/users              User list (HTMX-searchable)
GET        /admin/users/<uid>        User detail with registration history
POST       /admin/users/<uid>/toggle-admin  Toggle admin (cannot demote self or last admin)

GET  POST  /admin/email             Mass email composer

GET        /admin/logs              Activity log — paginated 50/page, newest first,
                                    filterable by action type
```

---

## Current Build Status

### Complete

**v1.0 (Phases 0–10)**
- Flask app factory, Docker, SQLite, Flask-Migrate, DaisyUI base template
- Five blueprints + health check + custom error pages (403/404/500)
- Full auth flow: register (honeypot), login, logout, email verification,
  password reset, unverified user banner
- Site settings with theme picker; admin guard via `before_request`
- Events CRUD (admin), public event listing and detail
- Ticket types CRUD; event clone action; status toggle
- Event registration with guards (sold out, closed, already registered, unverified)
- Registration confirmation email
- /dashboard and /events/<slug>/my-registration
- Admin registration list (filterable, HTMX search), registration detail
- Mark paid, mark comped, check-in/undo, admin notes, cancel, export CSV
- Seat management (admin bulk add/delete) and seat selection (user)
- Admin user list with search, user detail, toggle-admin
- Mass email composer
- Loaner equipment checkbox (needs_loaner on registration)

**v1.1 Complete**
- First-run onboarding wizard (/setup → /setup/site → /setup/complete)
- `before_request` guard redirects all routes to /setup when no admin exists
  or `setup_complete` is not "true"
- Event schedule (admin CRUD + HTMX add, public display on event detail)
- Potluck signup (user add/delete on my-registration, public display on event detail)
- Loaner equipment chooser (specific PC selection on my-registration,
  /admin/equipment CRUD, /admin/events/<id>/loaners approval/denial)
- Check-in mode (/admin/events/<id>/checkin — HTMX search, inline check-in)
- Event announcements (admin post/delete on event detail hub, public display)

**v1.2 Complete**
- Game suggestions + voting (confirmed attendees only; toggle vote; sorted by votes desc)
- BGG XML API and Steam store API game search/detail (game_lookup.py)
- Game enrichment on suggestion: image, description, year, min/max players
- HTMX-powered /games/search for game lookup during suggestion creation
- Visual seat map with real-time HTMX claim/release (seats_grid_partial.html)
- Custom registration questions (text/boolean/select, required flag, per-event)
- Custom question answers stored in RegistrationAnswer, exported in CSV
- Answers editable from my-registration page after the fact
- Discord OAuth login/link/disconnect (Authlib, credentials in site_settings)
- Google OAuth login/link/disconnect (Authlib, credentials in site_settings)
- Steam OpenID login/link/disconnect (python3-openid)
- New Steam users without an account complete registration via
  /auth/steam/complete-registration (provide email + password)
- Steam API key optional — without it, Steam username shows as "Steam User"
- Stripe payment integration (server-side Checkout Sessions, webhook handler)
- PayPal payment integration (Orders API v2, webhook handler with signature verification)
- Payment processor choice at registration (stripe/paypal/pay later)
- `stripe_session_id`, `paypal_order_id`, `payment_processor` fields on Registration

**v1.3 Complete**
- Challonge tournament integration (challonge.py + full admin UI):
  create, participants (from attendees or manual), start, reset, open matches,
  report match results, delete
- Attendees can self-sign-up / withdraw via /events/<slug>/tournaments/<tid>/signup
- Challonge API credentials configured in admin settings
- General activity logging — `activity_log` table, `activity.py`, `/admin/logs` view
  paginated 50/page, filterable by action type
- Passkeys (WebAuthn) — passkey registration, login, and removal; `webauthn_credentials`
  table; WebAuthn routes in routes/auth.py; `passkeys_enabled` site setting

Still planned for v1.3 (not yet built):
- Location map embed — `location_map_embed_url` field on events, iframe on event detail

**v1.4b Complete**
- Optional TOTP two-factor authentication — `pyotp` + `qrcode[pil]` dependencies;
  `totp_secret` and `totp_backup_codes` columns on users; migration applied
- Setup flow: QR code shown as data URI (no disk writes), secret stored in session
  until verified, 8 backup codes generated on enable
- Login intercept: password-based and passkey logins redirect to `/auth/2fa/verify`
  when user has 2FA enabled; 5-attempt lockout clears session
- Backup codes: single-use, hashed with Werkzeug, count shown on security page
  with warning when 0 or 1 remaining; regeneration requires password confirmation
- Disable requires password confirmation; all 20 tests in `tests/test_2fa.py` pass

---

## Future Features Backlog

### Immediate Next Features (build before August event)

- **First + Last name + Gamertag**: Split users.name into first_name and last_name.
  Add gamertag TEXT NULLABLE. Update registration form to collect all three.
  Gamertag used everywhere user-facing. Real name in admin only.
  Migration splits existing name on first space.

- **Potluck per-day**: Add event_date DATE NULLABLE to potluck_items. Multi-day
  events show per-day sections ("Friday Potluck", "Saturday Potluck"). Migration
  required (batch alter).

- **Admin registration notification email**: Send to contact_email when
  registration confirmed. Include attendee name, ticket type, payment status,
  event name. Silent failure — registration succeeds even if notification fails.

- **Emergency contact decoupled from lodging**: Add collect_emergency_contacts
  boolean to events. Remove lodging-based conditional. Migration required.

- **Game suggestion detail modal**: Add play_style, system_requirements, notes to
  GameSuggestion. Detail button on each card opens DaisyUI modal via HTMX showing
  full game info including voter list (gamertags), current price and historical low
  via ITAD, Steam link, BGG link. Migration required.

- **Gamertag everywhere user-facing**: Audit all templates. Replace any display of
  user.name in public/attendee contexts with user.gamertag (fallback:
  user.first_name). Seat maps, attendee lists, voter lists, tournament brackets,
  potluck items.

- **Markdown rendering**: Add mistune to requirements.txt. Add a markdown Jinja2
  filter. Apply to: event description, short description, announcements, schedule
  descriptions, loaner specs, game suggestion notes, potluck descriptions. Remove
  `| safe` from these fields. Add "Supports Markdown" hint to admin forms for these
  fields.

- **Event countdown**: JavaScript countdown on homepage (next event card) and event
  detail page. Shows days/hours remaining. Hides after event starts. No backend
  change.

- **Add to Calendar**: Button on event detail page generates and downloads an .ics
  file. One route, one Python stdlib method. Works with Google Calendar, Apple
  Calendar, Outlook.

- **Default game search tab by event type**: LAN events open Steam tab by default.
  Board game events open BGG tab by default. One line of template logic using
  event.type.

---

### Near-term (after event, when time allows)

- **Markdown for custom question help text**: If help/hint text is added to
  EventQuestion in future, render as Markdown.

- **Custom color overrides**: site_settings keys for primary, secondary, accent
  colors. Injected as CSS variable overrides in base.html inline style block
  targeting DaisyUI variables. Admin color picker inputs on settings page.

- **Image upload for branding**: Replace logo_url and favicon_url text fields with
  file upload. Store in static/uploads/branding/. Validate MIME type, size. Show
  requirements (PNG/SVG, max 2MB, suggested dimensions).

- **Registration confirmation resend**: Admin button on registration detail page to
  re-trigger confirmation email.

- **Post-event feedback**: Rating (1-5) + optional comment, unlocked for attendees
  after end_datetime. New event_feedback table. Admin sees aggregate on event hub.

- **Profile photo from OAuth**: On OAuth login/connect, if no avatar_url is set,
  pull the provider's avatar URL (Steam: avatarfull, Discord: avatar hash URL,
  Google: picture from userinfo). Store as avatar_url. User can override via URL
  field on profile page.

- **Event countdown improvements**: If the event is currently running, show
  "Event is live!" instead of countdown.

---

### Medium-term

- **STL generation**: Per-attendee seat name tag and trophy nameplate STL files
  downloadable from admin seat management page. OpenSCAD via subprocess. Deferred
  pending organizer providing OpenSCAD design reference files. Do not design
  geometry independently.

- **Seat reservation hold during Stripe checkout**: Soft-reserve chosen seat for
  10 minutes when Stripe checkout initiated. Release on timeout or cancellation.
  Prevents race condition on last seat.

- **3D printed nametag SVG export**: Low priority. SVG template with gamertag,
  per-attendee, ZIP download for admin.

---

### Long-term / Research required

- **Eventula database migration**: One-time migration script mapping Eventula
  (MySQL/PostgreSQL, Laravel schema) to Ludus (SQLite). Research task before
  implementation. Run on test instance first.

- **FinallyGames rebrand**: Replace Ludus branding with FinallyGames branding via
  admin settings. No code change — update site_name, logo_url, color settings.

- **QR code check-in scanner UI**: Camera-based scanner on
  /admin/events/<id>/checkin. html5-qrcode from CDN. Deferred from v1.3.

- **Child/guardian registration**: Minor registrations under a parent account.
  Requires careful schema design.

- **Self-hosted photo gallery**: event_images table (id, event_id, image_url,
  caption, display_order). Admin curates highlights post-event. Grid on event page.

- **GDPR data export**: User downloads archive of their personal data. One route,
  JSON or ZIP.

- **Coupon codes**: CouponCode model with discount logic. Applied at registration.
  Explicitly deferred — not forgotten.

- **Pre-event survey**: Custom questions already handle this. No separate feature
  needed.

---

## Key Design Decisions

**Mail settings stored in site_settings, not .env**
All mail configuration (server, port, TLS, username, password,
default sender) is stored in site_settings and configurable via
the admin UI. This allows changing email providers (Gmail,
Microsoft 365, Zoho, etc.) without SSH access. mailer.py reads
from SiteSettings dynamically before each send rather than from
app.config at startup. The only env vars are SECRET_KEY,
FLASK_APP, and DATABASE_URL. mail_password is stored in the
database — acceptable for a personal home server where the
operator is the only admin.

**is_admin boolean, not a roles table**
Only two permission levels exist: admin and user. If a third level is ever
needed, add it then. Don't build a permissions system speculatively.

**Capacity computed, not stored**
`events` has no `capacity` field. Capacity = sum of `quantity_total` across
active ticket types. Always accurate, never out of sync.

**quantity_sold computed, not stored**
Count active (non-cancelled) registrations per ticket type at query time.
Implemented as a property on `TicketType`.

**valid_days as JSON text**
Stored as a JSON array of ISO date strings on ticket_types. Generated from the
event's start/end date range in the admin UI (checkboxes for each day). No
separate days table.

**Seat availability computed, not stored**
A seat is taken if any non-cancelled registration has seat_id = that seat's id.

**One registration per user per event**
Enforced by UNIQUE(user_id, event_id) on registrations.

**No anonymous registrations**
Users must have an account to register for events.

**No friend registration**
One user registers themselves only. Not a current feature.

**Unverified users**
Can log in but see a persistent banner. Cannot register for events.
Unverified accounts older than 7 days should be cleaned up periodically.

**Day pass seat assignment**
Day pass holders do NOT pre-assign seats. First-come-first-served at the door.
Only seatable weekend pass holders claim seats in advance.

**Sensitive config in env vars, display/integration config in site_settings**
SMTP credentials, app secret key → .env
Site name, theme, social links, feature toggles, OAuth credentials,
Stripe keys, PayPal keys, Challonge keys → site_settings table

**Admin panel always uses data-theme="dim"**
Regardless of any theme settings. Hard-coded in base.html for /admin/* routes.

**Theme resolution (v1.4a)**
Theme is resolved in priority order: per-user `preferred_theme` → OS
`prefers-color-scheme` media query (dark → `default_dark_theme` setting, light →
`default_light_theme` setting) → `ui_theme` as a no-JS fallback. The logic lives
in a small inline `<script>` in `base.html`'s `<head>`, injected only on non-admin
pages, which calls `document.documentElement.setAttribute('data-theme', ...)` before
CSS loads to prevent flash. Admin pages always render with `data-theme="dim"` via the
static `<html>` attribute — the script does not run on `/admin/*` routes.

The `inject_site_settings` context processor exposes `ui_theme`, `default_dark_theme`,
and `default_light_theme` to all templates. The `allowed_themes` site setting (newline-
separated list) restricts which themes users may choose; empty means all 16 curated
themes are allowed. `get_allowed_themes()` in `models.py` enforces this filter and is
the single authoritative source for that list.

**What to bring lives in description**
No separate `what_to_bring` field. Operators include it in the event description.

**Gallery is a link, not file storage**
`events.gallery_url` links to a Google Photos shared album. If set, the event
detail page shows a "View Photos" link. Users can join the album from within
Google Photos. Do not attempt to iframe or embed Google Photos — they block it
with X-Frame-Options. No separate join URL field. No file upload in scope.

**Location renders as a Google Maps link; optional embed for a map tile**
The `location` text value is always wrapped in a `google.com/maps?q=` link on
the event detail page, supporting plain addresses and `lat,lng` coordinates.
`location_map_embed_url` (planned v1.3) optionally adds an iframe map tile above
that link. Admin pastes only the src URL from the Google Maps embed dialog.

**Activity logging covers admin writes only, not reads**
`activity.py` provides a single `log()` function. Only the curated list of
admin-initiated write actions defined in the roadmap is logged. Reads, user
self-service actions, and automated system events are not logged. The log is
append-only — no update or delete routes exist for `activity_log` rows.

**TOTP secret is stored in session during setup, not DB, until verified**
`/account/security/setup` generates a `pyotp` secret and stores it in the Flask
session. It is only persisted to `users.totp_secret` after the user submits a
valid TOTP code via `/account/security/verify`. This prevents half-configured
2FA state in the database.

**Email verification tokens and password reset tokens are hashed**
Always store hashed (SHA-256 via `_hash_token`). Never store raw tokens in the
database.

**checkin_code**
UUID generated at registration time. Used as a future QR code payload.
The scanner UI is not yet built — the field is populated now.

**mailer.py not email.py**
Named `mailer.py` to avoid shadowing the Python standard library `email` module.

**render_as_batch=True in migrations/env.py**
SQLite does not support `ALTER COLUMN` or `DROP COLUMN` natively. Alembic's
`render_as_batch=True` tells it to use the "batch" migration strategy (copy table,
recreate with changes). This is set in `migrations/env.py` and must not be removed.

**Webhook routes are CSRF exempt**
`/account/stripe/webhook` and `/account/paypal/webhook` use `@csrf.exempt`
imported from `extensions.py`. Payment providers POST to these endpoints without
a CSRF token. Never add CSRF checking to webhook endpoints.

**OAuth via Authlib (Discord, Google); Steam via python3-openid**
Discord and Google use OAuth 2.0 / OIDC implemented with Authlib's Flask
integration. Steam uses OpenID 2.0 (a different protocol) implemented with
`python3-openid`. The `oauth` object in `extensions.py` is for Authlib only;
Steam routes use `openid.consumer.consumer.Consumer` directly.

**OAuth credentials live in site_settings, not .env**
`discord_oauth_client_id`, `discord_oauth_client_secret`, `google_oauth_client_id`,
`google_oauth_client_secret` are stored in the `site_settings` table and edited
via the admin settings page. This allows the operator to configure OAuth without
restarting Docker.

**BGG uses XML API 2, parsed with stdlib xml.etree.ElementTree**
No third-party BGG library. BGG may return HTTP 202 (data queued for generation)
on thing lookup — `get_bgg_game` sleeps 2 seconds and retries once.

**Steam store search uses undocumented but stable store API**
`search_steam` calls `https://store.steampowered.com/api/storesearch/` — this
endpoint requires no API key and has been stable for years. It is not the
official Steam Web API.

**Stripe uses server-side Checkout Sessions (no Stripe.js needed)**
`payments.py` creates a Checkout Session via the Stripe Python SDK and redirects
the user to `session.url`. No client-side JavaScript is required beyond the
redirect.

**PayPal uses Orders API v2 via requests**
No PayPal SDK — raw HTTP calls via the `requests` library. `paypal_mode` setting
controls sandbox vs. live URL base.

**Challonge API uses requests with api_key query param; degrade gracefully**
The Challonge API v1 authenticates via `?api_key=...` on every request.
All functions in `challonge.py` raise `requests.RequestException` on error.
Callers in routes wrap calls in `try/except http_requests.RequestException` and
either flash an error or proceed with local deletion, so the app works even if
Challonge is unreachable.

**game_lookup.search_games catches all errors; individual functions raise**
The lower-level functions (`search_bgg`, `search_steam`, `get_bgg_game`,
`get_steam_game`) call `raise_for_status()` and may raise. `search_games` is
the safe public API — it silently catches exceptions from both sources and
returns whatever results were collected. Routes always call `search_games` for
search; they wrap `get_bgg_game` / `get_steam_game` in try/except individually.

**password_hash is nullable**
Users created via OAuth (Discord, Google, Steam) start with no password.
`User.has_password` returns False for these users. They must set a password
via `/account/set-password` before they can disconnect their last OAuth provider.

**Gamertag is the universal user-facing identity**
The gamertag field on users is shown everywhere attendees are visible to other
attendees: seat maps, attendee lists, voter lists on game suggestions, potluck
signups, tournament brackets and participant lists. Real names (first_name +
last_name) are only shown in admin views. No exceptions. If a user has no
gamertag set, fall back to first_name only (never full name in public contexts).
Admins see full name in all admin routes.

**First name + Last name (not full name)**
The users table stores first_name and last_name separately. The User model has a
`name` @property returning `f"{self.first_name} {self.last_name}"` for backwards
compatibility in admin contexts. The registration form collects first and last name
separately. Migration splits existing name on first space. Name search in admin
routes searches both columns.

**HTML for emails only. Markdown everywhere else.**
Transactional emails (confirmation, notification, reset) and mass email use HTML
with plain-text fallback. Already implemented. All admin-entered text fields that
display to users on the site use Markdown rendered via mistune: event description,
event short description, event announcements, schedule item descriptions, loaner
equipment specs, game suggestion notes, potluck item descriptions, custom question
help text (if added). Admin forms show a "Supports Markdown" hint on these fields.
The `| safe` filter is removed from non-email content. mistune added to
requirements.txt.

**Game suggestion detail modal**
Game suggestion cards on the event detail page show minimal info: game image,
name, vote count, and a "Details" button. Clicking "Details" opens a DaisyUI
modal loaded via HTMX (lazy, fetched on open not on page load). The modal shows
the full game record: description, play_style (co-op/competitive/both), min/max
players, voter list (gamertags of users who upvoted), current price and historical
low via ITAD, system_requirements, notes, Steam link, BGG link. This replaces the
organizer's manual game spreadsheet.

**GameSuggestion additional fields**
GameSuggestion model adds: play_style TEXT NULLABLE ('co-op', 'competitive',
'both'), system_requirements TEXT NULLABLE (freetext, e.g. "Low", "Medium/High",
"Requires controller"), notes TEXT NULLABLE (context from the suggester).
Migration required. The suggestion form on the event page exposes these fields.

**Potluck is per-day**
PotluckItem adds event_date DATE NULLABLE. When an event spans multiple days, the
add-item form shows a day selector (same date range logic as ticket valid_days).
The potluck section on the event detail page and my-registration page groups items
by day: "Friday Potluck", "Saturday Potluck". Single-day events show no grouping.

**Admin receives email on registration**
When any registration is confirmed, send a notification email to
SiteSettings.get("contact_email"). Include: attendee name, ticket type, payment
status, event name. Sent via mailer.py, wrapped in try/except (failure is silent
— registration must succeed even if notification fails). This is in addition to
the existing confirmation email sent to the attendee.

**Emergency contact decoupled from lodging**
The event model adds collect_emergency_contacts BOOLEAN DEFAULT FALSE. Emergency
contact fields appear on the registration form when this flag is True, regardless
of whether any ticket type has includes_lodging. The admin event create/edit form
has a checkbox: "Collect emergency contact information from attendees". Remove the
existing conditional that tied emergency contacts to lodging ticket types.
Migration required (batch alter on events).

**No Discord webhook feature**
The Discord webhook integration idea is removed from the backlog. The organizer
does not use Discord for community management — it is used only for voice channels
during the event.

**STL generation — deferred pending design reference**
Programmatic STL generation for seat name tags and trophy nameplates is a planned
feature. OpenSCAD via subprocess is the intended implementation approach. Feature
is deferred until the organizer provides finalized OpenSCAD design files as a
reference. Do not design the geometry — wait for the reference. Once provided,
generate per-attendee STLs downloadable from the admin seat management page.

---

## DaisyUI Themes

The admin settings page presents a curated list, not all 35 themes.

**Dark themes (default audience):**
dark, dracula, night, synthwave, halloween, forest, black, luxury, dim

**Light themes:**
light, cupcake, retro, garden, lofi, autumn, nord

Default theme on first install: `dark` (controlled by `ui_theme` site setting).

The admin settings page shows a single theme select. v1.4 will add separate dark/light
selects and per-user theme preference with `allowed_themes` restriction.

---

## Bot/Spam Prevention

Two layers, both required:

1. **Honeypot field** on the register form. A hidden input (visually hidden via
   CSS class, NOT `display:none` or `type=hidden` — bots detect those). Field
   name is `website`. If the field has any value on submission, silently reject
   and show success (do not tell the bot it failed).

2. **Email verification required** before registering for events.

Cloudflare Turnstile may be added later if needed. Do not add reCAPTCHA v2.

---

## Coding Conventions

**`_BOOL_SETTINGS` invariant (critical)**
Every BooleanField in `AdminSettingsForm` in `forms.py` must have its field name
listed in `_BOOL_SETTINGS` in `routes/admin.py`. If a BooleanField is not in
`_BOOL_SETTINGS`, the settings form stores Python `True`/`False` instead of the
string `"true"`/`"false"`, silently breaking every `SiteSettings.get(...) == "true"`
check. When adding any new BooleanField to `AdminSettingsForm`, add its name to
`_BOOL_SETTINGS` in the same commit. Comments in both files point to this dependency.

**State-changing routes must use POST only**
Every route that creates, updates, or deletes database records must declare
`methods=["POST"]`. GET requests must never modify state. Certain GET routes are
legitimate exceptions due to external protocol constraints (email links, OAuth/OpenID
callbacks, payment processor return URLs) — these must have a comment explaining
why GET is acceptable. When adding a new state-changing route, verify
`methods=["POST"]` is explicit and add a test that GET returns 405.

**Cross-file consistency**
When a constant set, list, or allowlist in one file must stay synchronized with
definitions in another file, add a comment in both files naming the dependency.
Never update one without the other. Example: `_VALID_PROVIDERS` in `routes/auth.py`
is duplicated as inline literals in `routes/account.py`; both files carry comments
pointing to each other.

**Silent exception handling**
Every `except` clause that catches broadly (e.g., `except Exception`) must call
`current_app.logger.warning(f"<context>: {e}")` before the fallback return.
Intentional exceptions to this rule: (1) `activity.log()` — documented as
never-crash by design; (2) email sends in registration routes — best-effort, a
failed email must not prevent the registration from succeeding.

**Gamertag vs name rule**
In any template or route that displays user identity to other users (not admins),
use `user.gamertag` or fall back to `user.first_name`. Never use `user.name` in
public contexts. Admin routes and admin templates may use `user.name` (the full
name property) and display both first_name and last_name. This rule applies to:
attendee lists, seat maps, voter lists, potluck items, tournament brackets, game
suggestion cards.

**Markdown rendering**
Use the markdown Jinja2 filter (via mistune) for all admin-entered text fields
that render to users on the site. HTML is used for emails only. When adding a new
text field that will display to users, default to Markdown unless there is a
specific reason for HTML.

---

## Email

All email is sent via Flask-Mail using SMTP credentials from env vars.

**Transactional emails:**
- Email verification (on account creation)
- Password reset
- Registration confirmation (on successful event registration, pay-later path)
- Registration pending payment (when Stripe or PayPal checkout is initiated)

**Mass email (admin /admin/email):**
- Admin composes subject + HTML body
- Selectable recipients (by event + payment status filter, or all users)
- Sent inline (no background task queue)

---

## Docker Setup

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:create_app()"]
```

```yaml
# docker-compose.yml
services:
  app:
    build: .
    restart: unless-stopped
    volumes:
      - ./data:/app/data
      - ./static/uploads:/app/static/uploads
    ports:
      - "8000:8000"
    env_file: .env
```

SQLite file lives at `/app/data/ludus.db` inside the container,
mapped to `./data/ludus.db` on the host. Back up this file.

---

## Environment Variables

The .env file contains only three values:

```
SECRET_KEY=      # Required. Signs sessions. Generate with:
                 # python3 -c "import secrets; print(secrets.token_hex(32))"
FLASK_APP=app    # Required for flask CLI commands.
DATABASE_URL=sqlite:///data/ludus.db
```

Everything else — mail, payments, OAuth, APIs, site config —
is configured through the admin settings UI and stored in
site_settings.

---

## CLI Commands

```
flask create-admin <email>   # Promote an existing user to admin by email
flask seed-settings          # Seed site_settings with defaults (idempotent)
flask seed-setup             # Reset setup_complete=false (re-run wizard, dev use only)
flask seed-event             # Seed one published test LAN event (idempotent)
flask db migrate -m "msg"    # Generate migration from model changes
flask db upgrade             # Apply pending migrations
```

---

## Testing

### Stack
- `pytest` 9.0.3 and `pytest-flask` 1.3.0 — both in `requirements.txt`
- Tests live in `tests/` at the project root
- Test database is always in-memory SQLite — never touches `data/ludus.db`

### Test Count
**431 tests** across 15 test files. Run `pytest --collect-only -q | tail -1` for the current count.

### Folder Structure
```
tests/
├── conftest.py           # Fixtures (see below)
├── test_admin.py         # 72 tests — admin routes, mark paid/comped, check-in,
│                         #            seat assignment, custom questions admin
├── test_auth.py          # 14 tests — register, login, verification, password reset
├── test_events.py        # 20 tests — registration rules, guards, cancellation
├── test_events_public.py # 19 tests — public event listing, event detail, attendee list
├── test_game_lookup.py   # 35 tests — BGG/Steam API functions, /games/search route,
│                         #            game enrichment on suggestion creation
├── test_oauth.py         # 28 tests — Discord/Google OAuth login and account linking
├── test_payments.py      # 27 tests — Stripe/PayPal checkout flows and webhooks
├── test_setup.py         # 16 tests — first-run wizard, setup guard redirect behavior
├── test_steam.py         # 20 tests — Steam OpenID login, account link/disconnect
├── test_v11.py           # 44 tests — schedule, potluck, loaner equipment,
│                         #            announcements, check-in mode
├── test_v12.py           # 25 tests — game suggestions + voting, visual seat map
├── test_v13.py           # 35 tests — Challonge tournament CRUD, participants, matches
├── test_v14.py           # 15 tests — activity logging, location link, logout POST guard
├── test_passkeys.py      # 21 tests — WebAuthn registration, login, removal, malformed JSON
└── test_2fa.py           # 20 tests — TOTP 2FA login flow, setup, disable, backup codes
```

### conftest.py Fixtures
```python
app()                 # In-memory SQLite; seeds setup_complete=true + a setup admin
                      # so the before_request setup guard does not redirect every test.
client(app)           # Flask test client
admin_user(app)           # Verified admin (email: admin@example.com, pass: adminpass123)
regular_user(app)         # Verified non-admin (email: user@example.com, pass: userpass123)
unverified_user(app)      # Unverified non-admin (email: unverified@example.com)
oauth_user(app)           # OAuth-only user (no password, Discord account linked)
published_event(app)      # Published LAN event 90 days out, seating enabled
draft_event(app)          # Draft board_game event (not publicly visible)
past_event(app)           # Published board_game event in the past
ticket_type(app, published_event)    # $20 Weekend Pass, qty 30, seatable
seat(app, published_event)           # Single seat "Seat 1"
registration(app, regular_user, published_event, ticket_type)
                                     # Confirmed, unpaid registration
discord_settings(app)     # Seeds Discord OAuth credentials in site_settings
```

### What to Test
Focus on paths where a silent bug would be catastrophic:

**Auth**
- Unverified users cannot register for events
- Verified users can log in; wrong password is rejected
- Password reset token expires and cannot be reused
- Honeypot field rejection on register

**Registration rules**
- User cannot register for the same event twice
- Cannot register when a ticket type is sold out
- Cannot register when `registration_open = False`
- Cannot register when `registration_closes_at` is in the past
- Confirmation email is triggered on successful registration

**Admin guard**
- Every `/admin/*` route returns 302 redirect for non-admin users
- Every `/admin/*` route returns 200 for admin users

**Admin actions**
- Marking paid updates `payment_status` and `paid_at`
- Marking comped sets `payment_status = 'comped'`
- Check-in sets `checked_in_at`
- Cancelling frees the seat

### Running Tests
```bash
pytest                        # All tests
pytest tests/test_auth.py     # One file
pytest -v                     # Verbose output
```

---

## Git and Development Workflow

### What Is Gitignored
```
.env                  # Never commit secrets
data/                 # Never commit the database (contains personal data)
__pycache__/
*.pyc
.venv/
venv/
static/uploads/
.DS_Store
```

`migrations/` is NOT gitignored. It is code — commit it.
`.env.example` is NOT gitignored. It documents required variables — commit it.

### Commit Conventions
- Commit at the end of each working feature, not each file save
- Every commit should leave the app in a working, runnable state
- Message format: imperative mood, short, descriptive
  - Good: `Add email verification flow`
  - Good: `Phase 3: Events read-only pages complete`
  - Bad: `wip`, `stuff`, `fix`

### Development Workflow
Two modes depending on context:

**Flask dev server** — use this during active development (90% of the time):
```bash
source venv/bin/activate
flask run --debug
```
Code changes reload instantly. No Docker rebuild needed. Runs on port 5000.

**Docker** — use this at the end of each phase and before any deployment:
```bash
docker compose up --build
```
Tests the full production-like stack. Runs on port 8000.

Never use `flask run` in production. Always use Gunicorn via Docker on the
home server.

---

## What NOT to Build

The following are explicitly out of scope. Do not implement, do not suggest:

- Shop or merchandise system
- Credit or points system
- Forum or discussion board
- User-to-user messaging
- Badges or gamification
- Orga team management UI
- Multiple seating plans per event
- Intranet / live event mode
- Full audit logging (every DB write) — the planned Activity Logging feature covers only a curated list of admin write actions
- Multi-tenant / multi-organization support
- Additional OAuth/OpenID providers beyond Discord, Google, Steam — not in scope
- Coupon codes — explicitly deferred, not forgotten
- QR code scanner UI — checkin_code is stored, scanner UI deferred
- Self-hosted photo gallery — gallery_url is a link; file upload deferred
- Child/guardian registration — deferred, no schema support
- Background task queue (Celery, RQ) — not needed at this scale
- Caching layer (Redis, Memcached) — not needed at this scale
- WebSockets — not needed
- REST API — not needed
- Any frontend framework (React, Vue, Svelte, Alpine beyond minor use)
- Any CSS requiring a build step
- News posts — listed in v1.1 roadmap but not implemented; not a priority
