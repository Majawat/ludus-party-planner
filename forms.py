from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateTimeLocalField,
    DecimalField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional

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


class EventForm(FlaskForm):
    name = StringField("Event Name", validators=[DataRequired(), Length(max=200)])
    slug = StringField("URL Slug", validators=[Optional(), Length(max=200)])
    type = SelectField(
        "Event Type",
        choices=[("lan", "LAN Party"), ("board_game", "Board Game Night")],
        validators=[DataRequired()],
    )
    status = SelectField(
        "Status",
        choices=[("draft", "Draft"), ("published", "Published"), ("archived", "Archived")],
        validators=[DataRequired()],
    )
    short_description = StringField(
        "Short Description", validators=[Optional(), Length(max=300)]
    )
    description = TextAreaField("Full Description (HTML)", validators=[Optional()])
    start_datetime = DateTimeLocalField(
        "Start Date & Time", format="%Y-%m-%dT%H:%M", validators=[DataRequired()]
    )
    end_datetime = DateTimeLocalField(
        "End Date & Time", format="%Y-%m-%dT%H:%M", validators=[DataRequired()]
    )
    location = StringField("Location", validators=[DataRequired(), Length(max=300)])
    cover_image_url = StringField("Cover Image URL", validators=[Optional()])
    gallery_url = StringField("Gallery URL", validators=[Optional()])
    seating_enabled = BooleanField("Seating Enabled")
    registration_open = BooleanField("Registration Open")
    registration_closes_at = DateTimeLocalField(
        "Registration Closes At", format="%Y-%m-%dT%H:%M", validators=[Optional()]
    )


class TicketTypeForm(FlaskForm):
    name = StringField("Ticket Name", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[Optional()])
    price = DecimalField(
        "Price ($)", places=2, default=0.00, validators=[Optional(), NumberRange(min=0)]
    )
    quantity_total = IntegerField(
        "Total Quantity", validators=[DataRequired(), NumberRange(min=1)]
    )
    seatable = BooleanField("Grants a Seat (LAN events)")
    includes_lodging = BooleanField("Includes Lodging")
    max_per_user = IntegerField(
        "Max Per User", default=1, validators=[DataRequired(), NumberRange(min=1)]
    )
    is_active = BooleanField("Active (available for purchase)")
    # valid_days handled via request.form.getlist("valid_days") in routes —
    # checkboxes are generated dynamically from the event's date range


class EventRegistrationForm(FlaskForm):
    ticket_type_id = SelectField("Ticket Type", coerce=int, validators=[DataRequired()])
    emergency_contact_name = StringField("Emergency Contact Name", validators=[Optional(), Length(max=200)])
    emergency_contact_phone = StringField("Emergency Contact Phone", validators=[Optional(), Length(max=50)])
    submit = SubmitField("Register")


class AdminMarkPaidForm(FlaskForm):
    payment_method = SelectField(
        "Payment Method",
        choices=[("cash", "Cash"), ("venmo", "Venmo"), ("paypal", "PayPal"), ("other", "Other")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Mark Paid")


class AdminNotesForm(FlaskForm):
    admin_notes = TextAreaField("Admin Notes", validators=[Optional()])
    submit = SubmitField("Save Notes")


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
