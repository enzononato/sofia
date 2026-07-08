"""
Shared pytest configuration for the pure/unit test suite.

No database fixtures live here on purpose: every test in this suite exercises
deterministic, in-memory logic (string splitting, CRM stage transitions,
context-block formatting, etc.) and never touches Postgres or the network.
"""
