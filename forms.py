from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional

_THEME_CHOICES = [
    ("dark", "Dark"),
    ("dracula", "Dracula"),
    ("night", "Night"),
    ("synthwave", "Synthwave"),
    ("halloween", "Halloween"),
    ("forest", "Forest"),
    ("black", "Black"),
    ("luxury", "Luxury"),
    ("dim", "Dim"),
    ("light", "Light"),
    ("cupcake", "Cupcake"),
    ("retro", "Retro"),
    ("garden", "Garden"),
    ("lofi", "Lofi"),
    ("autumn", "Autumn"),
    ("nord", "Nord"),
]


class RegistrationForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo("password")]
    )
    newsletter_opt_in = BooleanField("Subscribe to newsletter")
    website = StringField("Website")  # honeypot — no validators


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember me")


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo("password")]
    )


class AdminSettingsForm(FlaskForm):
    site_name = StringField("Site Name", validators=[DataRequired()])
    site_tagline = StringField("Tagline", validators=[Optional()])
    contact_email = StringField("Contact Email", validators=[Optional(), Email()])
    logo_url = StringField("Logo URL", validators=[Optional()])
    favicon_url = StringField("Favicon URL", validators=[Optional()])
    venmo_handle = StringField("Venmo Handle", validators=[Optional()])
    discord_url = StringField("Discord URL", validators=[Optional()])
    twitch_url = StringField("Twitch URL", validators=[Optional()])
    youtube_url = StringField("YouTube URL", validators=[Optional()])
    instagram_url = StringField("Instagram URL", validators=[Optional()])
    facebook_url = StringField("Facebook URL", validators=[Optional()])
    terms_of_service = TextAreaField("Terms of Service", validators=[Optional()])
    privacy_policy = TextAreaField("Privacy Policy", validators=[Optional()])
    registration_enabled = BooleanField("Registration Enabled")
    show_upcoming_event_on_homepage = BooleanField("Show Upcoming Event on Homepage")
    ui_theme = SelectField("Site Theme", choices=_THEME_CHOICES)
