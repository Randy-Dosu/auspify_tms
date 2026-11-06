"""Development entry point.

Run with:  python run.py
Production: use a WSGI server, e.g.  waitress-serve --port=5000 run:app
"""

import os

from app import create_app

# Exposed at module level so `flask --app run run` / `run:app` also work.
app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",  # reachable from the browser preview / LAN
        port=app.config["PORT"],
        debug=app.config["DEBUG"],  # False unless APP_DEBUG=1
        use_reloader=False,  # avoids double-starting background workers
    )
