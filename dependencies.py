from typing import Any

from fastapi import Request


def get_graph(request: Request) -> Any:
    return request.app.state.graph
