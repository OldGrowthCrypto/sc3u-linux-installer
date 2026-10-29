# Command line interface (used by tests and for headless installs). SPDX-License-Identifier: GPL-3.0-or-later
import argparse, sys
from . import core
def main(argv=None):
    ap = argparse.ArgumentParser(prog="sc3u-linux-installer-cli")
    sp = ap.add_subparsers(dest="cmd", required=True)
    for n in ("install", "add-files"):
        p = sp.add_parser(n); p.add_argument("source", nargs="?" if n == "install" else None)
        p.add_argument("--lang", default="en", choices=list(core.LANGS)); p.add_argument("--no-bat", action="store_true"); p.add_argument("--no-intro", action="store_true"); p.add_argument("--windowed", action="store_true"); p.add_argument("--stretch", action="store_true"); p.add_argument("--res", default="auto", choices=["auto", "1280x1024", "1024x768", "800x600"])
    sp.add_parser("status"); sp.add_parser("uninstall"); v = sp.add_parser("validate"); v.add_argument("source")
    sp.add_parser("files-to-copy")
    a = ap.parse_args(argv)
    if a.cmd == "validate": ok, why, kind = core.validate_source(a.source); print(("OK " if ok else "NO ") + why); return 0 if ok else 1
    if a.cmd == "status":
        st, p, m = core.install_state(); print(st, p["game"]); [print("missing:", x) for x in core.missing_game_data(p["game"], (m or {}).get("lang"))] if m else None; return 0
    if a.cmd == "files-to-copy": print(core.MANUAL_COPY.format(game=core.paths()["game"])); return 0
    if a.cmd == "uninstall": core.uninstall(); return 0
    o = {"lang": a.lang, "bat": not a.no_bat, "intro": not a.no_intro, "fullscreen": not a.windowed, "resolution": a.res, "stretch": a.stretch}
    if a.cmd == "install":
        core.install_runtime(o)
        if a.source: core.add_game_data(a.source, o)
    else: core.add_game_data(a.source, o)
    return 0
if __name__ == "__main__": sys.exit(main())
