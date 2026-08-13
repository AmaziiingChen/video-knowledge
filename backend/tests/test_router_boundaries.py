import ast
from pathlib import Path

from fastapi import FastAPI
from router_registry import API_ROUTERS, register_api_routers


def test_routers_do_not_import_other_router_modules():
    routers_dir = Path(__file__).resolve().parents[1] / "routers"
    violations = []
    for path in sorted(routers_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("routers"):
                violations.append(f"{path.name}:{node.lineno}:{node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("routers"):
                        violations.append(f"{path.name}:{node.lineno}:{alias.name}")
    assert violations == []


def test_router_registry_has_unique_tags_and_registers_core_routes():
    tags = [tag for _router, tag in API_ROUTERS]
    assert len(tags) == len(set(tags))

    app = FastAPI()
    register_api_routers(app)
    paths = {
        f"/api{route.path}"
        for router, _tag in API_ROUTERS
        for route in router.routes
    }
    assert {
        "/api/tasks",
        "/api/inbox",
        "/api/ingest/link",
        "/api/content/{item_id}/article-preview",
    } <= paths
