"""Email + password auth. No email verification at this stage — an account
is just a unique email and a hashed password."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


class AuthError(Exception):
    """Raised for user-facing auth failures (bad credentials, taken email)."""


def register(session: Session, email: str, password: str) -> db.User:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AuthError("Enter a valid email address.")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")

    existing = session.scalar(select(db.User).where(db.User.email == email))
    if existing is not None:
        raise AuthError("An account with that email already exists.")

    user = db.User(email=email, password_hash=generate_password_hash(password))
    session.add(user)
    session.commit()
    return user


def authenticate(session: Session, email: str, password: str) -> db.User:
    email = email.strip().lower()
    user = session.scalar(select(db.User).where(db.User.email == email))
    if user is None or not check_password_hash(user.password_hash, password):
        raise AuthError("Incorrect email or password.")
    return user
