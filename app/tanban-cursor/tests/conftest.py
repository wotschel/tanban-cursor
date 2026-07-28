"""Ensure config import during collection has a usable DATABASE_URL."""

import os

os.environ.setdefault("DATABASE_URL", "mysql+pymysql://tanban_cursor:test@localhost/tanban_cursor")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("CURSOR_ACTIVE", "false")
