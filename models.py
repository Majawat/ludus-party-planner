import hashlib
import json
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "event"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    email = db.Column(db.Text, nullable=False, unique=True)
    password_hash = db.Column(db.Text, nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    newsletter_opt_in = db.Column(db.Boolean, default=False, nullable=False)
    avatar_url = db.Column(db.Text, nullable=True)
    email_verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    platform_accounts = db.relationship("UserPlatformAccount", back_populates="user")
    passkey_credentials = db.relationship(
        "WebAuthnCredential",
        backref="user",
        lazy="select",
        cascade="all, delete-orphan",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def has_password(self):
        return self.password_hash is not None

    @property
    def is_verified(self):
        return self.email_verified_at is not None


class EmailVerificationToken(db.Model):
    __tablename__ = "email_verification_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    token_hash = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

    user = db.relationship("User", backref="verification_tokens")

    @classmethod
    def create_for_user(cls, user):
        raw_token = secrets.token_urlsafe(32)
        record = cls(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=utcnow() + timedelta(hours=48),
        )
        db.session.add(record)
        return raw_token


class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    token_hash = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref="reset_tokens")

    @classmethod
    def create_for_user(cls, user):
        raw_token = secrets.token_urlsafe(32)
        record = cls(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.session.add(record)
        return raw_token

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > utcnow()


class UserPlatformAccount(db.Model):
    __tablename__ = "user_platform_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "platform"),
        UniqueConstraint("platform", "platform_user_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    platform = db.Column(db.Text, nullable=False)
    username = db.Column(db.Text, nullable=False)
    platform_user_id = db.Column(db.Text, nullable=True)

    user = db.relationship("User", back_populates="platform_accounts")


class WebAuthnCredential(db.Model):
    __tablename__ = "webauthn_credentials"

    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    credential_id = db.Column(db.Text, nullable=False, unique=True)
    public_key    = db.Column(db.Text, nullable=False)
    sign_count    = db.Column(db.Integer, nullable=False, default=0)
    device_name   = db.Column(db.Text, nullable=True)
    aaguid        = db.Column(db.Text, nullable=True)
    created_at    = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_used_at  = db.Column(db.DateTime, nullable=True)


class SiteSettings(db.Model):
    __tablename__ = "site_settings"

    key = db.Column(db.Text, primary_key=True)
    value = db.Column(db.Text, nullable=False)

    @classmethod
    def get(cls, key, default=None):
        row = db.session.get(cls, key)
        return row.value if row else default

    @classmethod
    def set(cls, key, value):
        row = db.session.get(cls, key)
        if row:
            row.value = value
        else:
            db.session.add(cls(key=key, value=value))
        db.session.commit()

    @classmethod
    def all_as_dict(cls):
        return {r.key: r.value for r in cls.query.all()}


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    slug = db.Column(db.Text, nullable=False, unique=True)
    type = db.Column(db.Text, nullable=False)  # 'lan' or 'board_game'
    status = db.Column(db.Text, nullable=False, default="draft")  # 'draft', 'published', 'archived'
    description = db.Column(db.Text, nullable=True)
    short_description = db.Column(db.Text, nullable=True)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.Text, nullable=False)
    cover_image_url = db.Column(db.Text, nullable=True)
    gallery_url = db.Column(db.Text, nullable=True)
    seating_enabled = db.Column(db.Boolean, default=False, nullable=False)
    registration_open = db.Column(db.Boolean, default=True, nullable=False)
    registration_closes_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    ticket_types = db.relationship(
        "TicketType",
        back_populates="event",
        order_by="TicketType.id",
        cascade="all, delete-orphan",
    )
    registrations = db.relationship(
        "Registration",
        back_populates="event",
        order_by="Registration.created_at",
    )
    schedule_items = db.relationship(
        "EventScheduleItem",
        back_populates="event",
        order_by="EventScheduleItem.starts_at",
        cascade="all, delete-orphan",
    )
    potluck_items = db.relationship(
        "PotluckItem",
        back_populates="event",
        cascade="all, delete-orphan",
    )
    announcements = db.relationship(
        "EventAnnouncement",
        back_populates="event",
        order_by="EventAnnouncement.created_at",
        cascade="all, delete-orphan",
    )
    game_suggestions = db.relationship(
        "GameSuggestion",
        back_populates="event",
        cascade="all, delete-orphan",
    )
    questions = db.relationship(
        "EventQuestion",
        back_populates="event",
        order_by="EventQuestion.display_order",
        cascade="all, delete-orphan",
    )
    tournaments = db.relationship(
        "Tournament",
        back_populates="event",
        cascade="all, delete-orphan",
    )

    @property
    def capacity(self):
        return sum(t.quantity_total for t in self.ticket_types if t.is_active)

    @property
    def is_upcoming(self):
        return self.start_datetime > utcnow()

    @property
    def type_label(self):
        return "LAN Party" if self.type == "lan" else "Board Game Night"


class TicketType(db.Model):
    __tablename__ = "ticket_types"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    name = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)
    quantity_total = db.Column(db.Integer, nullable=False)
    seatable = db.Column(db.Boolean, default=False, nullable=False)
    includes_lodging = db.Column(db.Boolean, default=False, nullable=False)
    valid_days = db.Column(db.Text, nullable=False)  # JSON array of ISO date strings
    max_per_user = db.Column(db.Integer, default=1, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    event = db.relationship("Event", back_populates="ticket_types")
    registrations = db.relationship("Registration", back_populates="ticket_type")

    @property
    def valid_days_list(self):
        try:
            return json.loads(self.valid_days)
        except (ValueError, TypeError):
            return []

    @property
    def quantity_sold(self):
        return Registration.query.filter(
            Registration.ticket_type_id == self.id,
            Registration.status != "cancelled",
        ).count()


class Seat(db.Model):
    __tablename__ = "seats"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    label = db.Column(db.Text, nullable=False)
    display_order = db.Column(db.Integer, nullable=False, default=0)

    event = db.relationship("Event", backref="seats")


class Registration(db.Model):
    __tablename__ = "registrations"
    __table_args__ = (UniqueConstraint("user_id", "event_id"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey("ticket_types.id"), nullable=False)
    seat_id = db.Column(db.Integer, db.ForeignKey("seats.id"), nullable=True)
    status = db.Column(db.Text, nullable=False, default="pending")
    payment_status = db.Column(db.Text, nullable=False, default="unpaid")
    payment_method = db.Column(db.Text, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    checked_in_at = db.Column(db.DateTime, nullable=True)
    checkin_code = db.Column(db.Text, nullable=False, unique=True)
    needs_loaner = db.Column(db.Boolean, default=False, nullable=False)
    emergency_contact_name = db.Column(db.Text, nullable=True)
    emergency_contact_phone = db.Column(db.Text, nullable=True)
    terms_accepted_at = db.Column(db.DateTime, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    stripe_session_id = db.Column(db.Text, nullable=True)
    paypal_order_id = db.Column(db.Text, nullable=True)
    payment_processor = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    user = db.relationship("User", backref="registrations")
    event = db.relationship("Event", back_populates="registrations")
    ticket_type = db.relationship("TicketType", back_populates="registrations")
    seat = db.relationship("Seat", backref="registrations")
    answers = db.relationship(
        "RegistrationAnswer",
        back_populates="registration",
        cascade="all, delete-orphan",
    )


class EventScheduleItem(db.Model):
    __tablename__ = "event_schedule_items"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=True)
    display_order = db.Column(db.Integer, nullable=False, default=0)

    event = db.relationship("Event", back_populates="schedule_items")


class PotluckItem(db.Model):
    __tablename__ = "potluck_items"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    registration_id = db.Column(db.Integer, db.ForeignKey("registrations.id"), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    event = db.relationship("Event", back_populates="potluck_items")
    registration = db.relationship("Registration", backref="potluck_items")


class LoanerEquipment(db.Model):
    __tablename__ = "loaner_equipment"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)
    specs = db.Column(db.Text, nullable=True)
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    requests = db.relationship("LoanerRequest", back_populates="equipment")


class LoanerRequest(db.Model):
    __tablename__ = "loaner_requests"

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registrations.id"), nullable=False)
    equipment_id = db.Column(db.Integer, db.ForeignKey("loaner_equipment.id"), nullable=True)
    status = db.Column(db.Text, nullable=False, default="requested")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    registration = db.relationship("Registration", backref=db.backref("loaner_requests", lazy="dynamic"))
    equipment = db.relationship("LoanerEquipment", back_populates="requests")


class EventAnnouncement(db.Model):
    __tablename__ = "event_announcements"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    title = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    event = db.relationship("Event", back_populates="announcements")
    author = db.relationship("User", backref="announcements")


class GameSuggestion(db.Model):
    __tablename__ = "game_suggestions"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    suggested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    game_name = db.Column(db.Text, nullable=False)
    bgg_id = db.Column(db.Integer, nullable=True)
    steam_app_id = db.Column(db.Integer, nullable=True)
    game_image_url = db.Column(db.Text, nullable=True)
    game_description = db.Column(db.Text, nullable=True)
    game_year = db.Column(db.Integer, nullable=True)
    game_min_players = db.Column(db.Integer, nullable=True)
    game_max_players = db.Column(db.Integer, nullable=True)
    suggested_datetime = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    event = db.relationship("Event", back_populates="game_suggestions")
    suggester = db.relationship("User", backref="game_suggestions")
    votes = db.relationship(
        "GameSuggestionVote",
        back_populates="suggestion",
        cascade="all, delete-orphan",
    )


class GameSuggestionVote(db.Model):
    __tablename__ = "game_suggestion_votes"
    __table_args__ = (UniqueConstraint("suggestion_id", "user_id"),)

    id = db.Column(db.Integer, primary_key=True)
    suggestion_id = db.Column(db.Integer, db.ForeignKey("game_suggestions.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    suggestion = db.relationship("GameSuggestion", back_populates="votes")
    voter = db.relationship("User", backref="suggestion_votes")


class EventQuestion(db.Model):
    __tablename__ = "event_questions"
    __table_args__ = (UniqueConstraint("event_id", "field_name"),)

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.Text, nullable=False, default="text")
    field_name = db.Column(db.Text, nullable=False)
    is_required = db.Column(db.Boolean, default=False, nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)
    options = db.Column(db.Text, nullable=True)  # JSON array, only used for "select" type

    event = db.relationship("Event", back_populates="questions")
    answers = db.relationship("RegistrationAnswer", back_populates="question")

    @property
    def options_list(self):
        if self.options:
            return json.loads(self.options)
        return []


class RegistrationAnswer(db.Model):
    __tablename__ = "registration_answers"
    __table_args__ = (UniqueConstraint("registration_id", "question_id"),)

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registrations.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("event_questions.id"), nullable=False)
    answer = db.Column(db.Text, nullable=True)

    registration = db.relationship("Registration", back_populates="answers")
    question = db.relationship("EventQuestion", back_populates="answers")


class Tournament(db.Model):
    __tablename__ = "tournaments"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    name = db.Column(db.Text, nullable=False)
    game_name = db.Column(db.Text, nullable=False)
    format = db.Column(db.Text, nullable=False, default="single elimination")
    description = db.Column(db.Text, nullable=True)
    challonge_id = db.Column(db.Integer, nullable=True)
    challonge_url_slug = db.Column(db.Text, nullable=True)
    challonge_full_url = db.Column(db.Text, nullable=True)
    status = db.Column(db.Text, nullable=False, default="pending")
    sign_ups_open = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    event = db.relationship("Event", back_populates="tournaments")
    participants = db.relationship(
        "TournamentParticipant",
        back_populates="tournament",
        cascade="all, delete-orphan",
    )


class TournamentParticipant(db.Model):
    __tablename__ = "tournament_participants"

    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey("tournaments.id"), nullable=False)
    registration_id = db.Column(db.Integer, db.ForeignKey("registrations.id"), nullable=True)
    challonge_participant_id = db.Column(db.Integer, nullable=True)
    display_name = db.Column(db.Text, nullable=False)
    seed = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    tournament = db.relationship("Tournament", back_populates="participants")
    registration = db.relationship("Registration", backref="tournament_participations")


def unique_field_name(question_text: str, event_id: int, exclude_id: int = None) -> str:
    base = slugify(question_text).replace("-", "_") or "question"
    base = base[:60]
    name, suffix = base, 2
    while True:
        q = EventQuestion.query.filter_by(event_id=event_id, field_name=name)
        if exclude_id is not None:
            q = q.filter(EventQuestion.id != exclude_id)
        if q.first() is None:
            return name
        name = f"{base}_{suffix}"
        suffix += 1


def unique_slug(base_slug: str, exclude_id: int = None) -> str:
    slug, n = base_slug, 2
    while True:
        q = Event.query.filter_by(slug=slug)
        if exclude_id is not None:
            q = q.filter(Event.id != exclude_id)
        if q.first() is None:
            return slug
        slug = f"{base_slug}-{n}"
        n += 1
