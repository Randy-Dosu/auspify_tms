"""Input validation schemas (marshmallow).

Schemas are deliberately strict about *shape* (types, lengths, required
fields) and lenient about nothing else. Unknown keys are EXCLUDED, which is
what makes mass assignment ("role": "admin" in a register body) a no-op.
"""

from marshmallow import EXCLUDE, Schema, ValidationError, fields, validate

from .security import is_valid_email, password_policy_error


class _Base(Schema):
    class Meta:
        unknown = EXCLUDE  # silently ignore unexpected keys (no mass assignment)


def _email(value: str) -> str:
    value = (value or "").strip().lower()
    if not is_valid_email(value):
        raise ValidationError("Enter a valid email address.")
    return value


def _password(value: str) -> str:
    error = password_policy_error(value)
    if error:
        raise ValidationError(error)
    return value


class RegisterSchema(_Base):
    """Public self-registration: students only.

    There is intentionally no ``role`` field - a client cannot choose its role.
    """

    full_name = fields.String(required=True, validate=validate.Length(min=2, max=120))
    email = fields.String(required=True, validate=_email)
    password = fields.String(required=True, validate=_password)


class LoginSchema(_Base):
    email = fields.String(required=True, validate=validate.Length(min=3, max=254))
    # No strength check on login: policy violations must not be distinguishable
    # from a wrong password.
    password = fields.String(required=True, validate=validate.Length(min=1, max=256))


class CreateUserSchema(_Base):
    """Admin-created accounts (any role)."""

    full_name = fields.String(required=True, validate=validate.Length(min=2, max=120))
    email = fields.String(required=True, validate=_email)
    password = fields.String(required=True, validate=_password)
    role = fields.String(
        required=True, validate=validate.OneOf(["admin", "teacher", "student"])
    )
