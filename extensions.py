from authlib.integrations.flask_client import OAuth
from flask_wtf.csrf import CSRFProtect

oauth = OAuth()
csrf = CSRFProtect()
