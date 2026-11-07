"""Development entry point.

Run with:  python run.py
Production: use a WSGI server, e.g.  waitress-serve --port=5000 run:app
"""

from werkzeug.serving import WSGIRequestHandler

from app import create_app

# Exposed at module level so `flask --app run run` / `run:app` also work.
app = create_app()


class ApiRequestHandler(WSGIRequestHandler):
    """Hide the server banner.

    Werkzeug advertises "Werkzeug/<version> Python/<version>" by default, which
    tells an attacker exactly which framework bugs to try. The dev server is
    often reachable over a network (preview, LAN), so it identifies itself
    generically. A production WSGI server must be configured the same way
    (see SECURITY_REPORT.md, "Deployment").
    """

    def version_string(self) -> str:  # noqa: D102 - inherited docstring
        return "auspify-tms"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",  # reachable from the browser preview / LAN
        port=app.config["PORT"],
        debug=app.config["DEBUG"],  # False unless APP_DEBUG=1
        use_reloader=False,  # avoids double-starting background workers
        request_handler=ApiRequestHandler,  # no framework/version banner
    )
