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


class SmsStudentSchema(_Base):
    """A student record pushed by the Student Management System.

    There is intentionally no ``role`` field: unknown keys are excluded, so the
    SMS cannot create an admin or a teacher through this API.
    """

    full_name = fields.String(required=True, validate=validate.Length(min=2, max=120))
    email = fields.String(required=True, validate=_email)
    # Required when the account is new; optional on an update, where a blank
    # password means "keep the existing credential".
    password = fields.String(load_default=None, allow_none=True, validate=_password)
    course = fields.String(load_default="", validate=validate.Length(max=120))
    student_number = fields.String(
        load_default=None, allow_none=True, validate=validate.Length(min=2, max=32)
    )
    is_active = fields.Boolean(load_default=True)


class SmsStudentStatusSchema(_Base):
    """Activate or deactivate a provisioned student."""

    email = fields.String(required=True, validate=_email)
    is_active = fields.Boolean(required=True)


class SmsStudentLookupSchema(_Base):
    email = fields.String(required=True, validate=_email)


class SmsHandshakeSchema(_Base):
    # The SMS picks the challenge, so the signed reply cannot be replayed from
    # an earlier handshake.
    challenge = fields.String(required=True, validate=validate.Length(min=16, max=128))


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


# ---------------------------------------------------------------------------
# Step 2: exams, questions, options, answers
# ---------------------------------------------------------------------------
from marshmallow import validates_schema  # noqa: E402  (grouped with the schemas below)

from .security import from_iso  # noqa: E402

QUESTION_TYPES = ["single_choice", "multiple_choice", "true_false"]


class OptionSchema(_Base):
    option_text = fields.String(required=True, validate=validate.Length(min=1, max=500))
    is_correct = fields.Boolean(load_default=False)


class QuestionSchema(_Base):
    question_text = fields.String(required=True, validate=validate.Length(min=5, max=2000))
    question_type = fields.String(required=True, validate=validate.OneOf(QUESTION_TYPES))
    marks = fields.Float(required=True, validate=validate.Range(min=0.01, max=1000))
    negative_marks = fields.Float(load_default=0, validate=validate.Range(min=0, max=1000))
    position = fields.Integer(load_default=None, allow_none=True, validate=validate.Range(min=0))
    options = fields.List(
        fields.Nested(OptionSchema), required=True, validate=validate.Length(min=2, max=6)
    )

    @validates_schema
    def check_question(self, data, **kwargs):
        """Business rules: correct answers, marks, option counts."""
        errors = {}
        options = data.get("options") or []
        correct = [o for o in options if o.get("is_correct")]
        qtype = data.get("question_type")

        if not correct:
            errors["options"] = ["At least one option must be marked correct."]
        elif qtype in ("single_choice", "true_false") and len(correct) != 1:
            errors["options"] = ["Exactly one option must be correct for this question type."]
        elif qtype == "true_false" and len(options) != 2:
            errors["options"] = ["True/false questions need exactly two options."]

        marks = data.get("marks")
        negative = data.get("negative_marks") or 0
        if marks is not None and negative is not None and negative > marks:
            errors["negative_marks"] = ["Negative marks cannot exceed the question marks."]

        if errors:
            raise ValidationError(errors)


class ExamSchema(_Base):
    title = fields.String(required=True, validate=validate.Length(min=3, max=200))
    description = fields.String(load_default="", validate=validate.Length(max=5000))
    subject = fields.String(load_default="", validate=validate.Length(max=100))
    duration_minutes = fields.Integer(required=True, validate=validate.Range(min=1, max=600))
    pass_marks = fields.Float(load_default=0, validate=validate.Range(min=0, max=100000))
    start_time = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=64))
    end_time = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=64))
    is_published = fields.Boolean(load_default=False)
    allow_retakes = fields.Boolean(load_default=False)

    @validates_schema
    def check_window(self, data, **kwargs):
        start_raw = data.get("start_time")
        end_raw = data.get("end_time")
        start = from_iso(start_raw) if start_raw else None
        end = from_iso(end_raw) if end_raw else None
        if start_raw and start is None:
            raise ValidationError({"start_time": ["Use an ISO-8601 date-time."]})
        if end_raw and end is None:
            raise ValidationError({"end_time": ["Use an ISO-8601 date-time."]})
        if start and end and end <= start:
            raise ValidationError({"end_time": ["end_time must be after start_time."]})


class AnswerSchema(_Base):
    question_id = fields.Integer(required=True, strict=True, validate=validate.Range(min=1))
    selected_option_ids = fields.List(
        fields.Integer(strict=True, validate=validate.Range(min=1)),
        load_default=list,
        validate=validate.Length(max=6),
    )
