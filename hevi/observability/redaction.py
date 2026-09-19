"""D7-J: secret redaction for logs.

``redact_secrets`` already exists for usage-ledger summaries; this adds a
logging filter so arbitrary ``logger.*`` calls cannot leak credentials either.
"""

from __future__ import annotations

import logging

from hevi.creative.layer4.usage_ledger import redact_secrets


class RedactionFilter(logging.Filter):
    """Rewrite log records in place, masking recognized secret patterns."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
            redacted = redact_secrets(rendered)
            if redacted != rendered:
                record.msg = redacted
                record.args = ()
        except Exception:  # never break logging
            return True
        return True


def install_redaction_filter(logger: logging.Logger | None = None) -> None:
    target = logger or logging.getLogger()
    if not any(isinstance(f, RedactionFilter) for f in target.filters):
        target.addFilter(RedactionFilter())


__all__ = ["RedactionFilter", "install_redaction_filter"]
