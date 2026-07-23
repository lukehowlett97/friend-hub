"""Focused tests for public-demo limits and guest identity behavior."""

import os

os.environ.setdefault("DEBUG", "false")

from app.domains.auth.service import AuthService
from app.domains.demo.service import allow_demo_session_request


def test_demo_session_limit_allows_initial_visitors():
    ip = "demo-test-initial"
    assert all(allow_demo_session_request(ip) for _ in range(12))


def test_demo_session_limit_blocks_excessive_creation():
    ip = "demo-test-limit"
    for _ in range(12):
        assert allow_demo_session_request(ip)
    assert not allow_demo_session_request(ip)


def test_demo_name_parts_are_human_readable():
    assert AuthService.DEMO_ADJECTIVES
    assert AuthService.DEMO_ANIMALS
    assert all(" " not in item for item in AuthService.DEMO_ADJECTIVES)
    assert all(" " not in item for item in AuthService.DEMO_ANIMALS)
