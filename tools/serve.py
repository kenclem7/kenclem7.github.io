"""Static file server for local preview of the site.

Exists only because of a port collision. Claude Code's .claude/launch.json sets autoPort, so when
3463 is already taken - which happens the moment a second session or worktree is serving this same
repo - it picks a free port instead and passes the choice in the PORT environment variable. But
`python -m http.server` takes its port as a positional argument and never looks at the environment,
so the preview would open the new port while the server sat on 3463, showing either nothing or the
OTHER session's copy of the tree. That failure looks like a broken page rather than a port mix-up,
which is what makes it worth a file.

Run it by hand with no arguments for 3463, or pass a port: `py tools/serve.py 8080`.
"""

import functools
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer, test

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    port = os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else "3463")
    try:
        port = int(port)
    except ValueError:
        sys.exit("serve.py: port must be a number, got %r" % port)

    # serve the repo root regardless of where this is invoked from, so the preview does not depend
    # on the caller's working directory
    handler = functools.partial(SimpleHTTPRequestHandler, directory=ROOT)
    test(HandlerClass=handler, ServerClass=ThreadingHTTPServer, port=port, bind="127.0.0.1")


if __name__ == "__main__":
    main()
