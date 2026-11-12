"""Business-logic services.

Each module owns one bounded context from the blueprint: registry, policy,
approvals, audit, and decisions. Routers stay thin and delegate here.
"""

from .audit import record_event  # noqa: F401  (re-exported for convenience)
