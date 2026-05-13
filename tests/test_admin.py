from models import SiteSettings, db


ADMIN_ROUTES = [
    "/admin/",
    "/admin/settings",
]


def _login(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_admin_routes_redirect_unauthenticated(client):
    for route in ADMIN_ROUTES:
        response = client.get(route)
        assert response.status_code == 302, f"{route} should redirect unauthenticated users"
        assert "/login" in response.headers["Location"], f"{route} should redirect to login"


def test_admin_routes_return_403_for_non_admin(client, regular_user):
    _login(client, "user@example.com", "userpass123")
    for route in ADMIN_ROUTES:
        response = client.get(route)
        assert response.status_code == 403, f"{route} should return 403 for non-admin users"


def test_admin_routes_return_200_for_admin(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    for route in ADMIN_ROUTES:
        response = client.get(route)
        assert response.status_code == 200, f"{route} should return 200 for admin users"


def test_settings_saves_and_reads_back(client, admin_user):
    db.session.add(SiteSettings(key="ui_theme", value="dark"))
    db.session.add(SiteSettings(key="site_name", value="Ludus"))
    db.session.add(SiteSettings(key="site_tagline", value=""))
    db.session.add(SiteSettings(key="contact_email", value=""))
    db.session.add(SiteSettings(key="logo_url", value=""))
    db.session.add(SiteSettings(key="favicon_url", value=""))
    db.session.add(SiteSettings(key="venmo_handle", value=""))
    db.session.add(SiteSettings(key="discord_url", value=""))
    db.session.add(SiteSettings(key="twitch_url", value=""))
    db.session.add(SiteSettings(key="youtube_url", value=""))
    db.session.add(SiteSettings(key="instagram_url", value=""))
    db.session.add(SiteSettings(key="facebook_url", value=""))
    db.session.add(SiteSettings(key="terms_of_service", value=""))
    db.session.add(SiteSettings(key="privacy_policy", value=""))
    db.session.add(SiteSettings(key="registration_enabled", value="true"))
    db.session.add(SiteSettings(key="show_upcoming_event_on_homepage", value="true"))
    db.session.commit()

    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        "/admin/settings",
        data={
            "site_name": "My Event Site",
            "site_tagline": "Have fun",
            "contact_email": "",
            "logo_url": "",
            "favicon_url": "",
            "venmo_handle": "",
            "discord_url": "",
            "twitch_url": "",
            "youtube_url": "",
            "instagram_url": "",
            "facebook_url": "",
            "terms_of_service": "",
            "privacy_policy": "",
            "registration_enabled": "y",
            "ui_theme": "dracula",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    assert SiteSettings.get("ui_theme") == "dracula"
    assert SiteSettings.get("site_name") == "My Event Site"


def test_seed_settings_is_idempotent(app):
    with app.app_context():
        runner = app.test_cli_runner()

        result = runner.invoke(args=["seed-settings"])
        assert "16" in result.output

        result = runner.invoke(args=["seed-settings"])
        assert "0" in result.output


def test_create_admin_promotes_user(app, regular_user):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-admin", "user@example.com"])
    assert "now an admin" in result.output

    from models import User
    user = User.query.filter_by(email="user@example.com").first()
    assert user.is_admin is True


def test_create_admin_unknown_email(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-admin", "nobody@example.com"])
    assert "No user found" in result.output
