"""
The proxy has to carry Streamlit's websocket, or the app looks frozen.

This proxy is what took the session token out of the URL: Streamlit and
the API answer on one origin, so the HttpOnly cookie that replaced the
token is first-party. It landed as its own step, changing no
authentication, because a proxy fault and an auth change arriving
together are indistinguishable when something breaks.

It is now the only way in - the direct ports are gone - which turns every
assertion here from "the deployment is tidy" into "the product is
reachable and its sessions are safe".

What is asserted here is the handful of directives whose absence fails
silently. A Streamlit deployment behind a misconfigured proxy does not
error: the page loads, renders correctly, and then nothing responds to a
click, because the HTTP request succeeded and the websocket never
upgraded. There is no message anywhere. That is the failure this file
exists to prevent from shipping.

Text assertions on a config file are crude. They are also the only check
available without running nginx, and the alternative is trusting that six
directives are present because someone remembered them.
"""

from pathlib import Path

import pytest


CONFIG = (
    Path(__file__).resolve().parent.parent / "deploy" / "nginx.conf"
).read_text(encoding="utf-8")


def _location(path):
    """The body of one location block."""

    marker = f"location {path}"

    assert marker in CONFIG, f"there is no `{marker}` block"

    start = CONFIG.index(marker)
    body = CONFIG[start:]

    return body[:body.index("\n    }")]


def test_the_websocket_endpoint_is_proxied_at_all():
    """
    Streamlit talks to the browser over /_stcore/stream. Without it the
    page renders and then does nothing.
    """

    assert "location /_stcore/stream" in CONFIG


@pytest.mark.parametrize("directive", [
    "proxy_http_version 1.1",
    "proxy_set_header Upgrade",
    'proxy_set_header Connection "upgrade"',
])
def test_the_websocket_block_can_actually_upgrade(directive):
    """
    All three are required together. HTTP/1.1 plus both headers is what
    turns the request into a websocket; any one missing and the upgrade
    fails while the HTTP response still says 200.
    """

    assert directive in _location("/_stcore/stream")


def test_the_websocket_is_not_closed_while_a_user_reads():
    """
    A connection carrying no traffic is not an idle connection here - it
    is a consultant reading a case. nginx's 60s default would drop it and
    the page would stop responding with no error shown.
    """

    body = _location("/_stcore/stream")

    assert "proxy_read_timeout" in body

    seconds = int(
        body.split("proxy_read_timeout")[1].split("s;")[0].strip()
    )

    assert seconds >= 3600, (
        f"the websocket is dropped after {seconds}s of quiet, which is "
        f"less than someone spends reading one case"
    )


def test_the_api_prefix_is_stripped_before_it_reaches_the_app():
    """
    The trailing slash on proxy_pass is what removes /api from the
    forwarded path, so /api/health arrives as /health and the API keeps
    its routes unchanged. Without it every route would need an /api
    prefix compiled in, coupling the application to its deployment.
    """

    assert "proxy_pass http://api_upstream/;" in _location("/api/"), (
        "proxy_pass has no trailing slash, so /api/health reaches the "
        "API as /api/health and every route 404s"
    )


def test_the_api_and_streamlit_are_different_upstreams():

    assert "upstream api_upstream" in CONFIG
    assert "upstream streamlit_upstream" in CONFIG
    assert "server api:8501" not in CONFIG


def test_uploads_are_not_rejected_before_the_app_sees_them():
    """
    nginx defaults to 1m and returns 413 itself. A scanned passport PDF
    exceeds that easily, and the user would see the upload fail with no
    trace anywhere in the application logs.
    """

    assert "client_max_body_size" in CONFIG


# ------------------------------------------------------- compose ---

def _compose():

    import yaml

    return yaml.safe_load(
        (
            Path(__file__).resolve().parent.parent / "docker-compose.yml"
        ).read_text(encoding="utf-8")
    )


def test_the_proxy_waits_for_what_it_proxies():
    """
    Started first, nginx resolves neither upstream and exits. Both have
    healthchecks already, so this is condition: service_healthy rather
    than service_started - "the container is running" is not "Streamlit
    is answering".
    """

    proxy = _compose()["services"]["proxy"]

    for service in ("streamlit", "api"):
        assert proxy["depends_on"][service]["condition"] == "service_healthy"


def test_there_is_no_way_in_that_bypasses_the_proxy():
    """
    The direct ports are gone, and their absence is now load-bearing.

    They were published deliberately for one release, so that adding the
    proxy and removing them would not land together - a proxy fault and
    "the application is gone" arriving at the same moment have nothing to
    tell them apart.

    Now they have to stay gone. The session lives in a cookie the API
    sets, and a cookie can only be set on an origin where both halves
    answer. On http://localhost:8501 there is no /api/ path, so no cookie
    can be set there at all - and while the URL fallback still existed,
    that is precisely where a session token ended up back in the address
    bar and in the footer of every printed page. That is not a
    hypothetical: it is what was reported from a real printout, twice,
    the second time from :8501 after the proxy was already working.

    Asking everyone to use the right URL is not a control. Removing the
    other URL is.
    """

    services = _compose()["services"]

    for name in ("streamlit", "api"):

        assert not services[name].get("ports"), (
            f"{name} publishes a host port, so the application can be "
            f"reached on an origin where the session cookie cannot be "
            f"set - which is how the token gets back into the URL"
        )

    assert "80:80" in _compose()["services"]["proxy"]["ports"]


def test_the_api_is_told_the_prefix_nginx_strips():
    """
    --root-path must match the location block, or /docs breaks quietly.

    nginx removes /api before the API sees a request, so routing is
    unaffected either way. What breaks is every URL the application
    generates for itself: Swagger UI asks for the schema at an absolute
    path, so /api/docs would load and then request /openapi.json, which
    nginx sends to Streamlit. The page renders and reports "Failed to
    load API definition" - indistinguishable, to whoever is looking, from
    the API being down.

    Only reachable through the proxy now that the direct port is gone,
    which is what turns this from cosmetic into the only way in.
    """

    command = _compose()["services"]["api"]["command"]

    assert "--root-path /api" in " ".join(command.split()), (
        "the API does not know it is served under /api, so /docs loads "
        "and then fails to fetch its own schema"
    )

    assert "location /api/" in CONFIG


def test_the_config_is_mounted_read_only():
    """
    A container that can rewrite its own routing is a container whose
    routing is not in version control.
    """

    volumes = _compose()["services"]["proxy"]["volumes"]

    assert any(entry.endswith(":ro") for entry in volumes)
