"""Block outbound sockets so the suite cannot touch the network."""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise RuntimeError("tests must not access the network")

    monkeypatch.setattr(socket, "create_connection", blocked)
