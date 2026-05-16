import json
from flask import current_app, request as flask_request
from flask_login import current_user


def log(action, target_type=None, target_id=None, details=None):
    from models import db, ActivityLog
    try:
        entry = ActivityLog(
            user_id=current_user.id if current_user and current_user.is_authenticated else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=json.dumps(details) if details is not None else None,
            ip_address=flask_request.remote_addr,
        )
        db.session.add(entry)
        db.session.flush()  # caller owns the transaction
    except Exception as e:
        current_app.logger.warning(f"activity.log failed: {e}")
