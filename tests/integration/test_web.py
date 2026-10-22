"""前端静态契约、CSP 与安全头测试。"""

from __future__ import annotations

from html.parser import HTMLParser

from fastapi.testclient import TestClient

from roommate_billing.main import create_app


class _Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag, attrs) -> None:
        self.tags.append((tag, dict(attrs)))


def _parse(text: str) -> _Markup:
    parser = _Markup()
    parser.feed(text)
    return parser


def _has(tags, tag: str, **attrs: str) -> bool:
    return any(
        name == tag and all(values.get(key) == value for key, value in attrs.items())
        for name, values in tags
    )


def test_index_served_with_csp_and_no_inline_code() -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"

    markup = _parse(response.text)
    assert _has(markup.tags, "main", **{"data-testid": "app"})
    assert _has(markup.tags, "form", id="login-form")
    assert _has(markup.tags, "section", id="view-overview")
    assert _has(markup.tags, "form", id="agent-form")
    assert _has(markup.tags, "script", src="/assets/js/app.js", type="module")
    assert not any(tag == "script" and not attrs.get("src") for tag, attrs in markup.tags)
    assert not any("style" in attrs for _tag, attrs in markup.tags)
    assert not any(
        any(name.startswith("on") for name in attrs)
        for tag, attrs in markup.tags
        if tag not in {"script"}
    )
    assert "innerHTML" not in response.text


def test_assets_are_served() -> None:
    client = TestClient(create_app())
    for path, content_type in (
        ("/assets/app.css", "text/css"),
        ("/assets/js/app.js", "javascript"),
        ("/assets/js/api.js", "javascript"),
        ("/assets/js/format.js", "javascript"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert content_type in response.headers["content-type"], path
        assert response.headers["x-content-type-options"] == "nosniff"


def test_docs_not_blocked_by_csp() -> None:
    client = TestClient(create_app())
    response = client.get("/docs")
    assert response.status_code == 200
    assert "content-security-policy" not in response.headers
