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


class SeatForm(FlaskForm):
    label = StringField("Label", validators=[DataRequired(), Length(max=100)])
    display_order = IntegerField("Display Order", default=0, validators=[Optional()])
    submit = SubmitField("Add Seat")


class BulkSeatForm(FlaskForm):
    prefix = StringField("Label Prefix", default="Seat", validators=[DataRequired(), Length(max=50)])
    count = IntegerField("Count", validators=[DataRequired(), NumberRange(min=1, max=200)])
    start_number = IntegerField("Starting Number", default=1, validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField("Add Seats")


class AdminEmailForm(FlaskForm):
    event_id = SelectField("Event", coerce=int, validators=[Optional()])
    recipient_filter = SelectField(
        "Send To",
        choices=[
            ("all", "All registrants"),
            ("confirmed", "Confirmed (any payment)"),
            ("paid", "Paid only"),
            ("unpaid", "Unpaid only"),
            ("comped", "Comped only"),
        ],
    )
    subject = StringField("Subject", validators=[DataRequired(), Length(max=300)])
    body = TextAreaField("Body (HTML)", validators=[DataRequired()])
    submit = SubmitField("Send Emails")


class SetupAdminForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Create Admin Account")


class SetupSiteForm(FlaskForm):
    site_name = StringField("Site Name", validators=[DataRequired(), Length(max=200)])
    site_tagline = StringField("Tagline", validators=[Optional(), Length(max=300)])
    contact_email = StringField("Contact Email", validators=[Optional(), Email()])
    ui_theme = SelectField("Site Theme", choices=_THEME_CHOICES)
    submit = SubmitField("Save & Continue")


class ScheduleItemForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[Optional()])
    starts_at = DateTimeLocalField(
        "Starts At", format="%Y-%m-%dT%H:%M", validators=[DataRequired()]
    )
    ends_at = DateTimeLocalField(
        "Ends At", format="%Y-%m-%dT%H:%M", validators=[Optional()]
    )
    display_order = IntegerField("Display Order", default=0, validators=[Optional()])
    submit = SubmitField("Add Item")


class PotluckItemForm(FlaskForm):
    description = StringField(
        "What are you bringing?", validators=[DataRequired(), Length(max=300)]
    )
    submit = SubmitField("Add Item")


class LoanerEquipmentForm(FlaskForm):
    name = StringField("Equipment Name", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[Optional()])
    specs = TextAreaField("Specs", validators=[Optional()])
    is_available = BooleanField("Available")
    submit = SubmitField("Save")


class AnnouncementForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=200)])
    body = TextAreaField("Body", validators=[DataRequired()])
    submit = SubmitField("Post Announcement")


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
    discord_oauth_client_id = StringField("Discord Client ID", validators=[Optional()])
    discord_oauth_client_secret = StringField("Discord Client Secret", validators=[Optional()])
    google_oauth_client_id = StringField("Google Client ID", validators=[Optional()])
    google_oauth_client_secret = StringField("Google Client Secret", validators=[Optional()])
    steam_enabled = BooleanField("Enable Steam Login")
    steam_api_key = StringField("Steam API Key", validators=[Optional()])


class SetPasswordForm(FlaskForm):
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo("password", message="Passwords must match")]
    )
    submit = SubmitField("Set Password")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current Password", validators=[DataRequired()])
    new_password = PasswordField("New Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm New Password", validators=[DataRequired(), EqualTo("new_password", message="Passwords must match")]
    )
    submit = SubmitField("Change Password")


class OAuthConfirmLinkForm(FlaskForm):
    submit = SubmitField("Yes, link accounts")


class SteamCompleteRegistrationForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
    )
    submit = SubmitField("Create Account")


class GameSuggestionForm(FlaskForm):
    game_name = StringField("Game Name", validators=[DataRequired(), Length(max=300)])
    suggested_datetime = DateTimeLocalField(
        "Suggested Play Time", format="%Y-%m-%dT%H:%M", validators=[Optional()]
    )
    submit = SubmitField("Suggest Game")


class EventQuestionForm(FlaskForm):
    question_text = StringField("Question", validators=[DataRequired(), Length(max=500)])
    question_type = SelectField(
        "Type",
        choices=[("text", "Text"), ("boolean", "Yes / No"), ("select", "Multiple Choice")],
        validators=[DataRequired()],
    )
    is_required = BooleanField("Required")
    display_order = IntegerField("Display Order", default=0, validators=[Optional()])
    options = TextAreaField("Options (one per line)", validators=[Optional()])
    submit = SubmitField("Save")
