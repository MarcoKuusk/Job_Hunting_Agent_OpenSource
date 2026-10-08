"""Guards against JSON that Python will happily write but a browser refuses.

Python's json module emits bare `NaN`, `Infinity` and `-Infinity` tokens for
non-finite floats, and reads them back without complaint. JavaScript's
JSON.parse rejects them, and it rejects the WHOLE document: one such value
anywhere makes the entire response unreadable to the web UI.

This is not hypothetical. gspread turns a spreadsheet cell into a number
whenever the text looks like one, and `float("Infinity")` succeeds, so a
company genuinely called "Infinity" (or "NaN") became a non-finite float and
silently broke the matches list.

Pure stdlib, so the offline tests can cover it.
"""

from __future__ import annotations

import math
from typing import Any


def finite_only(value: Any) -> Any:
    """Return `value` with every non-finite float replaced by its text form.

    Containers are rebuilt, so the original is left untouched.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else _as_text(value)
    if isinstance(value, dict):
        return {key: finite_only(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_only(item) for item in value]
    return value


def _as_text(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"
