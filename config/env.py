"""Load local, single-line KEY=value settings without executing or expanding values.

Supports optional single/double quotes, comments and UTF-8 BOMs. Existing process
variables take precedence. Values are literal: no escapes or variable expansion.
"""
import os
import re


def load_local_env(path):
    try:
        contents = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return
    values = {}
    for number, raw_line in enumerate(contents.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid .env setting at line {number}; expected KEY=value.")
        if value.startswith(("'", '"')):
            end = value.find(value[0], 1)
            suffix = value[end + 1:].strip() if end >= 0 else ""
            if end < 0 or (suffix and not suffix.startswith("#")):
                raise ValueError(f"Invalid .env quotes at line {number}.")
            value = value[1:end]
        else:
            value = "" if value.startswith("#") else re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    # Parse first so a malformed file cannot apply only some of its settings.
    for key, value in values.items():
        os.environ.setdefault(key, value)
