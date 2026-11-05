"""Every request-scoped database session must commit BEFORE the response is sent.

FastAPI ends ``yield`` dependencies after the response by default, which would let a
client see 201 before the transaction commits (or fails). All uses of ``get_db`` must
declare ``scope="function"``; mixing scopes would also create two sessions per request.
"""

from fastapi.routing import APIRoute

from app.database import get_db
from app.main import app


def _walk(dependant, path):
    for sub in dependant.dependencies:
        if sub.call is get_db:
            yield path, sub.scope
        yield from _walk(sub, path)


def _api_routes(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        for attr in ("original_router", "router"):
            inner = getattr(route, attr, None)
            if inner is not None and hasattr(inner, "routes"):
                yield from _api_routes(inner.routes)
                break
        else:
            if hasattr(route, "routes") and not isinstance(route, APIRoute):
                yield from _api_routes(route.routes)


def test_get_db_is_function_scoped_everywhere():
    routes = {(r.path, tuple(sorted(r.methods or ()))): r for r in _api_routes(app.routes)}
    # Guard against a vacuous pass (FastAPI wraps included routers).
    assert len(routes) > 100
    offenders = []
    uses_db = 0
    for (path, _), route in routes.items():
        for _, scope in _walk(route.dependant, path):
            uses_db += 1
            if scope != "function":
                offenders.append((path, scope))
    assert uses_db > 50
    assert offenders == []


async def test_response_reflects_committed_state(client, customer):
    # The resource is committed by the time the 201 is returned: a new connection sees it.
    from app.database import async_session
    from app.models.vessel import Vessel

    r = await client.post(
        "/api/v1/vessels/",
        json={"nickname": "Commit", "make": "Rayglass", "model": "Legend 2500", "year": 2019},
        headers=customer.headers,
    )
    assert r.status_code == 201
    async with async_session() as s:
        assert await s.get(Vessel, __import__("uuid").UUID(r.json()["id"])) is not None
