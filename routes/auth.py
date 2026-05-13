from flask import Blueprint, render_template

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login")
def login():
    return render_template("auth/login.html")


@auth_bp.route("/register")
def register():
    return render_template("auth/register.html")


@auth_bp.route("/forgot-password")
def forgot_password():
    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>")
def reset_password(token):
    return render_template("auth/reset_password.html")


@auth_bp.route("/verify-email/<token>")
def verify_email(token):
    return "Email verified (placeholder)", 200
