"""Shared Flask extension instances.

Kept in their own module so route modules can use the same limiter instance
that the app factory initialises.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Per-IP rate limiter. Limits are attached per route (see routes/auth.py) and
# are configurable from the environment.
limiter = Limiter(key_func=get_remote_address)
