"""Opt-in diagnostics for recoverable failures, without changing fallback flow."""
import logging
import sys


def record_ignored_exception(module, source_line):
    """Record the exception type at DEBUG level; do not expose user paths/data."""
    try:
        logger = logging.getLogger('OrthoManager.recoverable')
        if logger.isEnabledFor(logging.DEBUG):
            exception_type = sys.exc_info()[0]
            logger.debug('Recovered in %s:%s (%s)', module, source_line,
                         exception_type.__name__ if exception_type else 'unknown')
    except Exception:
        # Logging must not break the existing recovery operation.
        return
