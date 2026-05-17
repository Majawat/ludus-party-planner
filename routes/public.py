from flask import Blueprint, current_app, render_template, abort, flash, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select, func

from forms import GameSuggestionForm
from game_lookup import get_bgg_game, get_itad_prices, get_steam_game, search_games
from models import db, Event, EventAnnouncement, EventScheduleItem, GameSuggestion, GameSuggestionVote, PotluckItem, Registration, SiteSettings, utcnow

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def index():
    upcoming_event = None
    if SiteSettings.get("show_upcoming_event_on_homepage", "true") == "true":
        upcoming_event = db.session.execute(
            select(Event)
            .filter_by(status="published")
            .where(Event.start_datetime > utcnow())
            .order_by(Event.start_datetime.asc())
            .limit(1)
        ).scalar_one_or_none()
    return render_template("public/index.html", upcoming_event=upcoming_event)


@public_bp.route("/events")
def events():
    all_events = db.session.execute(
        select(Event)
        .filter_by(status="published")
        .order_by(Event.start_datetime.desc())
    ).scalars().all()
    return render_template("public/events.html", events=all_events)


@public_bp.route("/events/<slug>")
def event_detail(slug):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)

    attendees = Registration.query.filter(
        Registration.event_id == event.id,
        Registration.status != "cancelled",
    ).all()

    user_registration = None
    if current_user.is_authenticated:
        user_registration = Registration.query.filter_by(
            user_id=current_user.id, event_id=event.id
        ).first()

    registration_is_open = (
        event.registration_open
        and (event.registration_closes_at is None or event.registration_closes_at > utcnow())
        and event.is_upcoming
    )

    schedule_items = (
        db.session.execute(
            db.select(EventScheduleItem)
            .where(EventScheduleItem.event_id == event.id)
            .order_by(EventScheduleItem.starts_at)
        )
        .scalars()
        .all()
    )

    potluck_items = (
        db.session.execute(
            db.select(PotluckItem)
            .where(PotluckItem.event_id == event.id)
            .join(PotluckItem.registration)
            .where(Registration.status != "cancelled")
            .order_by(PotluckItem.created_at)
        )
        .scalars()
        .all()
    )

    announcements = (
        db.session.execute(
            db.select(EventAnnouncement)
            .where(EventAnnouncement.event_id == event.id)
            .order_by(EventAnnouncement.created_at.desc())
        )
        .scalars()
        .all()
    )

    suggestions = (
        db.session.execute(
            db.select(GameSuggestion, func.count(GameSuggestionVote.id).label("vote_count"))
            .outerjoin(GameSuggestionVote, GameSuggestion.id == GameSuggestionVote.suggestion_id)
            .where(GameSuggestion.event_id == event.id)
            .group_by(GameSuggestion.id)
            .order_by(func.count(GameSuggestionVote.id).desc(), GameSuggestion.created_at.asc())
        )
        .all()
    )

    user_voted = set()
    if current_user.is_authenticated and suggestions:
        voted = GameSuggestionVote.query.filter_by(user_id=current_user.id).filter(
            GameSuggestionVote.suggestion_id.in_([row[0].id for row in suggestions])
        ).all()
        user_voted = {v.suggestion_id for v in voted}

    can_suggest = (
        current_user.is_authenticated
        and user_registration is not None
        and user_registration.status == "confirmed"
        and event.is_upcoming
    )
    suggestion_form = GameSuggestionForm() if can_suggest else None
    itad_enabled = bool(SiteSettings.get("itad_api_key", "").strip())

    return render_template(
        "public/event_detail.html",
        event=event,
        attendees=attendees,
        user_registration=user_registration,
        registration_is_open=registration_is_open,
        schedule_items=schedule_items,
        potluck_items=potluck_items,
        announcements=announcements,
        suggestions=suggestions,
        user_voted=user_voted,
        can_suggest=can_suggest,
        suggestion_form=suggestion_form,
        itad_enabled=itad_enabled,
    )


@public_bp.route("/events/<slug>/suggestions/add", methods=["POST"])
@login_required
def suggestion_add(slug):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)

    if not event.is_upcoming:
        abort(403)

    reg = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first()
    if reg is None or reg.status == "cancelled":
        abort(403)

    form = GameSuggestionForm()
    if form.validate_on_submit():
        bgg_id = request.form.get("bgg_id", type=int)
        steam_app_id = request.form.get("steam_app_id", type=int)

        image_url = description = year = min_p = max_p = None
        authoritative_name = form.game_name.data.strip()

        if bgg_id:
            try:
                details = get_bgg_game(bgg_id)
                if details:
                    authoritative_name = details["name"]
                    image_url = details.get("image_url")
                    description = details.get("description")
                    year = details.get("year")
                    min_p = details.get("min_players")
                    max_p = details.get("max_players")
            except Exception as e:
                current_app.logger.warning(f"BGG game lookup failed for id {bgg_id}: {e}")
        elif steam_app_id:
            try:
                details = get_steam_game(steam_app_id)
                if details:
                    image_url = details.get("image_url")
                    description = details.get("description")
            except Exception as e:
                current_app.logger.warning(f"Steam game lookup failed for id {steam_app_id}: {e}")

        duplicate = GameSuggestion.query.filter_by(
            event_id=event.id,
            suggested_by=current_user.id,
            game_name=authoritative_name,
        ).first()
        if duplicate:
            flash("You have already suggested that game for this event.", "warning")
        else:
            suggestion = GameSuggestion(
                event_id=event.id,
                suggested_by=current_user.id,
                game_name=authoritative_name,
                bgg_id=bgg_id,
                steam_app_id=steam_app_id,
                suggested_datetime=form.suggested_datetime.data or None,
                game_image_url=image_url,
                game_description=description,
                game_year=year,
                game_min_players=min_p,
                game_max_players=max_p,
            )
            db.session.add(suggestion)
            db.session.commit()
            flash("Game suggestion added!", "success")
    else:
        flash("Game name is required.", "error")

    return redirect(url_for("public.event_detail", slug=slug))


@public_bp.route("/events/<slug>/suggestions/<int:sid>/vote", methods=["POST"])
@login_required
def suggestion_vote(slug, sid):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)

    if not event.is_upcoming:
        abort(403)

    reg = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first()
    if reg is None or reg.status == "cancelled":
        abort(403)

    suggestion = db.session.get(GameSuggestion, sid)
    if suggestion is None or suggestion.event_id != event.id:
        abort(404)

    existing_vote = GameSuggestionVote.query.filter_by(
        suggestion_id=sid, user_id=current_user.id
    ).first()
    if existing_vote:
        db.session.delete(existing_vote)
        db.session.commit()
    else:
        vote = GameSuggestionVote(suggestion_id=sid, user_id=current_user.id)
        db.session.add(vote)
        db.session.commit()

    return redirect(url_for("public.event_detail", slug=slug))


@public_bp.route("/games/itad/<int:steam_app_id>")
def itad_prices(steam_app_id):
    if not request.headers.get("HX-Request"):
        abort(400)
    prices = get_itad_prices(steam_app_id)
    return render_template(
        "public/_itad_prices.html", prices=prices, steam_app_id=steam_app_id
    )


@public_bp.route("/games/search")
@login_required
def game_search():
    if not request.headers.get("HX-Request"):
        abort(400)
    q = request.args.get("q", "").strip()
    source = request.args.get("source", "all")
    try:
        results = search_games(q, source) if len(q) >= 2 else []
    except Exception as e:
        current_app.logger.warning(f"game_search failed for q={q!r}: {e}")
        results = []
    return render_template("public/game_search_results.html", results=results)
