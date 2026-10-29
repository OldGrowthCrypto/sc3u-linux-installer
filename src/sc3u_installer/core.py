# SC3U Linux Installer: core logic (no GUI). SPDX-License-Identifier: GPL-3.0-or-later
"""ISO validation, install planning and the install / add-game-files / uninstall steps.

Layout (identical for "install with ISO" and "install without ISO, add files later"):
  GAME  = ~/.local/share/sc3u-linux/game        runtime + game data
  ~/.local/bin/sc3u, sc3u-bat                    symlinks to GAME/sc3u-launch
  ~/.local/share/applications/sc3u-linux-*.desktop
No root is used except the optional sound fix (pkexec, run by the GUI)."""
import json, os, re, shutil, subprocess, tarfile, tempfile, time

LANGS = {  # code -> (label, res/text dir, sys.pak region)
    "en": ("English (US)", "english", "us"), "en_UK": ("English (UK)", "english-uk", "eu"),
    "de": ("Deutsch", "german", "eu"), "fr": ("Français", "french", "eu"),
    "it": ("Italiano", "italian", "eu"), "es": ("Español", "spanish", "eu"),
    "nl": ("Nederlands", "dutch", "eu"), "sv": ("Svenska", "swedish", "eu"),
    "pt": ("Português", "portuguese", "eu"),
}
DATA_DIRS = ["buildings", "cities", "res", "plugin"]
BAT_DIRS = ["barender", "bacustom"]
DATA_FILES = ["sc3u.ini", "snapshot.ini", "hotkeys.txt", "icon.xpm", "README", "Credits"]
# what must exist in GAME for the game to start
REQUIRED = ["sys/sys.pak", "res", "res/ui", "res/sound", "buildings", "cities", "sc3u.ini"]
MANIFEST = ".sc3u-install.json"
INTRO = "res/ui/shared/movies/intro.mpg"

def share_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (os.environ.get("SC3U_INSTALLER_SHARE"), os.path.join(here, "..", ".."), "/usr/share/sc3u-linux-installer"):
        if c and os.path.isdir(os.path.join(c, "payload")): return os.path.abspath(c)
    return "/usr/share/sc3u-linux-installer"

def paths(home=None):
    home = home or os.path.expanduser("~")
    xdg = os.environ.get("XDG_DATA_HOME") if home == os.path.expanduser("~") else None
    data = xdg or os.path.join(home, ".local/share")
    return {"home": home, "game": os.path.join(data, "sc3u-linux/game"), "bin": os.path.join(home, ".local/bin"),
            "apps": os.path.join(data, "applications"), "icons": os.path.join(data, "icons/hicolor/scalable/apps")}

# ---------------------------------------------------------------- sources
class SourceError(Exception): pass

def _run(cmd): return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout

def iso_listing(iso):
    if not shutil.which("isoinfo"): raise SourceError("The isoinfo tool is missing (package genisoimage).")
    try:
        info = _run(["isoinfo", "-d", "-i", iso]); files = _run(["isoinfo", "-R", "-f", "-i", iso]).splitlines()
    except subprocess.CalledProcessError: raise SourceError("This file is not a readable ISO image.")
    return info, set(files)

def iso_dirs(iso):
    """Set of directory paths in the ISO (including empty ones), from isoinfo -l."""
    out, cur = {"/"}, "/"
    for line in _run(["isoinfo", "-R", "-l", "-i", iso]).splitlines():
        if line.startswith("Directory listing of "): cur = line[21:].strip(); out.add(cur.rstrip("/") or "/"); continue
        m = re.match(r"^d\S+\s.*\]\s+(.+?)\s*$", line)
        if m and m.group(1) not in (".", ".."): out.add(cur.rstrip("/") + "/" + m.group(1))
    return out

def validate_listing(files, info=""):
    """files: set of '/x/y' paths. Returns (ok, reason, kind) kind=disc|game."""
    has = lambda p: ("/" + p) in files
    if has("bin/x86/glibc-2.1/sc3u") and has("sys/us/sys.pak") and has("res") :
        return True, "Loki Linux edition of SimCity 3000 Unlimited", "disc"
    if has("sys/sys.pak") and has("res") and has("buildings"):
        return True, "Copied game files", "game"
    if has("autorun.inf") or has("setup.exe") or has("win32"):
        if not has("bin/x86"):
            return False, "This looks like the Windows edition. You need the Loki Linux edition disc.", None
    return False, "This is not the Loki Linux edition of SimCity 3000 Unlimited (game files not found).", None

def validate_iso(iso):
    if not os.path.isfile(iso): return False, "File not found.", None
    try: info, files = iso_listing(iso)
    except SourceError as e: return False, str(e), None
    ok, why, kind = validate_listing(files, info)
    if ok and kind == "disc" and "Volume id: SC3U" not in info:
        why += " (unusual volume name, continuing)"
    return ok, why, kind

def dir_listing(d, depth=4):
    out = set()
    for dp, ds, fs in os.walk(d):
        rel = os.path.relpath(dp, d)
        if rel.count(os.sep) >= depth: ds[:] = []
        for n in ds + fs:
            out.add("/" + (n if rel == "." else rel + "/" + n))
    return out

def validate_source(p):
    if os.path.isdir(p):
        ok, why, kind = validate_listing(dir_listing(p))
        return ok, why, kind
    if p.lower().endswith(".iso") or os.path.isfile(p): return validate_iso(p)
    return False, "Not found.", None

class OpenSource:
    """Context manager yielding a directory for an ISO (read only loop mount via udisks,
    or isoinfo extraction into a temp dir) or a directory as is."""
    def __init__(self, src, log=print, tmp=None): self.src, self.log, self.tmp = src, log, tmp; self.loop = None; self.tmpdir = None
    def __enter__(self):
        if os.path.isdir(self.src): return self.src
        if shutil.which("udisksctl") and not os.environ.get("SC3U_NO_UDISKS"):
            try:
                out = _run(["udisksctl", "loop-setup", "-r", "-f", self.src, "--no-user-interaction"])
                self.loop = re.search(r"(/dev/loop\d+)", out).group(1); mp = ""
                for _ in range(20):
                    mp = _run(["lsblk", "-no", "MOUNTPOINT", self.loop]).strip()
                    if mp: break
                    time.sleep(0.25)
                if not mp:
                    _run(["udisksctl", "mount", "-b", self.loop, "-o", "ro", "--no-user-interaction"])
                    mp = _run(["lsblk", "-no", "MOUNTPOINT", self.loop]).strip()
                self.log("ISO opened read only at " + mp); return mp
            except Exception as e:
                self.log("Loop mount not available (%s), extracting with isoinfo instead" % str(e).strip()[:120]); self._close()
        _, files = iso_listing(self.src)
        self.tmpdir = tempfile.mkdtemp(prefix="sc3u-iso-", dir=self.tmp); dirs = iso_dirs(self.src)
        want = tuple("/" + x for x in DATA_DIRS + BAT_DIRS + ["sys"]) + tuple("/" + f for f in DATA_FILES)
        for f in sorted(files):
            if ".." in f.split("/") or not f.startswith(want): continue
            out = os.path.join(self.tmpdir, f.lstrip("/"))
            if f in dirs: os.makedirs(out, exist_ok=True); continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as fh: subprocess.run(["isoinfo", "-R", "-x", f, "-i", self.src], stdout=fh, check=True)
        return self.tmpdir
    def _close(self):
        if self.loop:
            subprocess.run(["udisksctl", "unmount", "-b", self.loop, "--no-user-interaction"], capture_output=True)
            subprocess.run(["udisksctl", "loop-delete", "-b", self.loop, "--no-user-interaction"], capture_output=True)
            self.loop = None
    def __exit__(self, *a):
        self._close()
        if self.tmpdir: shutil.rmtree(self.tmpdir, ignore_errors=True)

# ---------------------------------------------------------------- planning
def plan(opts, source_kind=None):
    """Return the ordered list of step ids for an install.
    opts: lang, bat, intro, with_data(bool). source_kind: disc|game|None."""
    s = ["check_space", "runtime", "patch_2_0a", "launcher", "menu"]
    if opts.get("with_data"):
        s += ["copy_data" if source_kind != "game_inplace" else "use_inplace", "region_sys_pak", "empty_dirs", "patch_2_0a_again"]
        if opts.get("lang") == "es": s.append("spanish_fix")
        if not opts.get("intro", True): s.append("drop_intro")
        s.append("verify")
    s.append("manifest")
    return s

def missing_game_data(game, lang=None):
    miss = [r for r in REQUIRED if not os.path.exists(os.path.join(game, r))]
    if lang and LANGS.get(lang) and not os.path.isdir(os.path.join(game, "res/text", LANGS[lang][1])):
        miss.append("res/text/" + LANGS[lang][1])
    elif not lang and os.path.isdir(os.path.join(game, "res")) and not any(
            os.path.isdir(os.path.join(game, "res/text", v[1])) for v in LANGS.values()):
        miss.append("res/text/<language>")
    return miss

def read_manifest(game):
    try:
        with open(os.path.join(game, MANIFEST)) as f: return json.load(f)
    except Exception: return None

def install_state(home=None):
    p = paths(home); m = read_manifest(p["game"])
    if not m: return "none", p, None
    return ("complete" if not missing_game_data(p["game"], m.get("lang")) else "runtime_only"), p, m

# ---------------------------------------------------------------- steps
def _extract(tarpath, dest):
    with tarfile.open(tarpath) as t: t.extractall(dest, filter="tar")

def _copy_filtered(src, dst, rels_dirs, rels_files, skip, log, progress=None):
    todo = []
    for r in rels_dirs:
        for dp, ds, fs in os.walk(os.path.join(src, r)):
            relp = os.path.relpath(dp, src)
            if skip(relp + "/"): ds[:] = []; continue
            os.makedirs(os.path.join(dst, relp), exist_ok=True)   # empty dirs matter (CD check)
            todo += [os.path.join(relp, f) for f in fs if not skip(os.path.join(relp, f))]
    todo += [f for f in rels_files if os.path.isfile(os.path.join(src, f))]
    for i, rel in enumerate(todo):
        d = os.path.join(dst, rel); os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(os.path.join(src, rel), d); os.chmod(d, 0o644)
        if progress and i % 200 == 0: progress(i / max(1, len(todo)))
    log("Copied %d game files" % len(todo)); return len(todo)

def install_runtime(opts, home=None, share=None, log=print):
    p = paths(home); share = share or share_dir(); game = p["game"]; pay = os.path.join(share, "payload")
    for need in ("patch-2.0a.tar", "loki_compat_libs-1_3.tar.bz2"):
        if not os.path.isfile(os.path.join(pay, need)): raise RuntimeError("Installer payload missing: " + need)
    os.makedirs(game, exist_ok=True)
    log("Installing compatibility runtime (Loki_Compat)"); _extract(os.path.join(pay, "loki_compat_libs-1_3.tar.bz2"), game)
    log("Installing update 2.0a (game program and libraries)"); _extract(os.path.join(pay, "patch-2.0a.tar"), game)
    _fix_modes(game)
    shutil.copyfile(os.path.join(share, "data/sc3u-launch"), os.path.join(game, "sc3u-launch")); os.chmod(os.path.join(game, "sc3u-launch"), 0o755)
    shutil.copyfile(os.path.join(share, "data/sc3u-game.svg"), os.path.join(game, "sc3u-game.svg"))
    cand = os.path.join(share, "sc3u-linux-installer")
    with open(os.path.join(game, ".installer-cmd"), "w") as f:
        f.write((cand if os.access(cand, os.X_OK) else "/usr/bin/sc3u-linux-installer") + "\n")
    log("Adding menu entries and commands")
    for d in (p["bin"], p["apps"], p["icons"]): os.makedirs(d, exist_ok=True)
    shutil.copyfile(os.path.join(share, "data/sc3u-game.svg"), os.path.join(p["icons"], "sc3u-linux-game.svg"))
    ents = [("sc3u", "SC3U (Linux)", "Play SimCity 3000 Unlimited, native Linux edition")]
    if opts.get("bat", True): ents.append(("sc3u-bat", "SC3U Building Architect (Linux)", "Design your own buildings"))
    for cmd, name, cmt in ents:
        link = os.path.join(p["bin"], cmd)
        if os.path.islink(link) or not os.path.exists(link):
            if os.path.lexists(link): os.unlink(link)
            os.symlink(os.path.join(game, "sc3u-launch"), link)
        with open(os.path.join(p["apps"], "sc3u-linux-%s.desktop" % cmd), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=%s\nComment=%s\nExec=%s\nIcon=sc3u-linux-game\n"
                    "Terminal=false\nCategories=Game;Simulation;\nStartupWMClass=sc3u\n" % (name, cmt, link))
    write_manifest(game, opts, data=False)

def _fix_modes(game):
    for b in ("sc3u", "sc3bat", "sc3u.dynamic", "sc3bat.dynamic", "sc3u-launch"):
        if os.path.exists(os.path.join(game, b)): os.chmod(os.path.join(game, b), 0o755)

def write_manifest(game, opts, data):
    m = read_manifest(game) or {}
    m.update({"version": 1, "lang": opts.get("lang", "en"), "bat": bool(opts.get("bat", True)),
              "intro": bool(opts.get("intro", True)), "fullscreen": bool(opts.get("fullscreen", True)), "resolution": opts.get("resolution", "auto"), "stretch": bool(opts.get("stretch", False)), "game_data": bool(data), "updated": time.strftime("%Y-%m-%d %H:%M:%S")})
    with open(os.path.join(game, MANIFEST), "w") as f: json.dump(m, f, indent=1)

def add_game_data(source, opts, home=None, share=None, log=print, progress=None, tmp=None):
    """Copy game data from an ISO, mounted disc, a folder of copied disc files, or the
    game folder itself (files copied in place), then apply update 2.0a on top."""
    p = paths(home); share = share or share_dir(); game = p["game"]; pay = os.path.join(share, "payload")
    if not read_manifest(game): install_runtime(opts, home, share, log)
    ok, why, kind = validate_source(source)
    inplace = os.path.isdir(source) and os.path.realpath(source) == os.path.realpath(game)
    if inplace: ok, kind = (os.path.isdir(os.path.join(game, "res")), "game")
    if not ok: raise SourceError(why)
    lang = opts.get("lang", "en"); _, textdir, region = LANGS[lang]
    with OpenSource(source, log, tmp) as src:
        if not inplace:
            def skip(rel):
                if rel.startswith("res/text/") and not rel.startswith("res/text/%s/" % textdir) and rel != "res/text/": return True
                if not opts.get("bat", True) and rel.startswith(("res/ba/", "barender/", "bacustom/")): return True
                return (not opts.get("intro", True)) and rel == INTRO
            log("Copying game files from " + source)
            _copy_filtered(src, game, DATA_DIRS + (BAT_DIRS if opts.get("bat", True) else []), DATA_FILES, skip, log, progress)
            os.makedirs(os.path.join(game, "sys"), exist_ok=True)
            pak = os.path.join(src, "sys", region, "sys.pak") if kind == "disc" else os.path.join(src, "sys/sys.pak")
            if not os.path.isfile(pak) and kind == "disc": pak = os.path.join(src, "sys/us/sys.pak")
            shutil.copyfile(pak, os.path.join(game, "sys/sys.pak"))
        else:
            sub = os.path.join(game, "sys", region, "sys.pak")
            if not os.path.isfile(os.path.join(game, "sys/sys.pak")) and os.path.isfile(sub):
                shutil.copyfile(sub, os.path.join(game, "sys/sys.pak"))
    for d in ("res/sound/radio/stations", "res/ba/ui/shared/dlg") if opts.get("bat", True) else ("res/sound/radio/stations",):
        os.makedirs(os.path.join(game, d), exist_ok=True)
    log("Applying update 2.0a"); _extract(os.path.join(pay, "patch-2.0a.tar"), game)
    if lang == "es" and os.path.isfile(os.path.join(pay, "spanish-patch-2.0a.tar")):
        log("Applying Spanish data fix"); _extract(os.path.join(pay, "spanish-patch-2.0a.tar"), game)
    if not opts.get("intro", True) and os.path.exists(os.path.join(game, INTRO)): os.remove(os.path.join(game, INTRO))
    _fix_modes(game)
    for dp, ds, fs in os.walk(game):
        for d in ds: os.chmod(os.path.join(dp, d), 0o755)
    miss = missing_game_data(game, lang)
    if miss: raise RuntimeError("Game files still missing: " + ", ".join(miss))
    write_manifest(game, opts, data=True); log("Game files complete")

def uninstall(home=None, keep_saves=True, log=print):
    p = paths(home); game = p["game"]
    if not read_manifest(game) and os.path.isdir(game): raise RuntimeError("Not our install, refusing to remove " + game)
    for cmd in ("sc3u", "sc3u-bat"):
        l = os.path.join(p["bin"], cmd)
        if os.path.islink(l) and os.readlink(l).startswith(game): os.unlink(l)
        f = os.path.join(p["apps"], "sc3u-linux-%s.desktop" % cmd)
        if os.path.exists(f): os.remove(f)
    ic = os.path.join(p["icons"], "sc3u-linux-game.svg")
    if os.path.exists(ic): os.remove(ic)
    if os.path.isdir(game): shutil.rmtree(game); log("Removed " + game)
    try: os.rmdir(os.path.dirname(game))
    except OSError: pass
    if keep_saves: log("Your saved cities in ~/.loki/sc3u were kept")

def free_space_ok(home=None, need_mb=1200):
    p = paths(home); d = p["game"]
    while not os.path.exists(d): d = os.path.dirname(d)
    return shutil.disk_usage(d).free // (1024 * 1024) >= need_mb

# ---------------------------------------------------------------- sound
def sound_status():
    dsp = os.path.exists("/dev/dsp"); w = dsp and os.access("/dev/dsp", os.W_OK)
    have = shutil.which("osspd") is not None or os.path.exists("/usr/sbin/osspd")
    return {"dsp": dsp, "writable": w, "osspd_installed": have, "ok": bool(w)}

SOUND_FIX = ("set -e; export DEBIAN_FRONTEND=noninteractive; "
             "dpkg -s osspd osspd-pulseaudio >/dev/null 2>&1 || apt-get install -y osspd osspd-pulseaudio; "
             "modprobe cuse || true; systemctl enable --now osspd.service")
def sound_fix_cmd(): return ["pkexec", "sh", "-c", SOUND_FIX]

MANUAL_COPY = """From the disc (or a mounted ISO) copy these into
  {game}

  buildings/      whole folder
  cities/         whole folder
  res/            whole folder (you may keep only your language in res/text/)
  plugin/         whole folder
  barender/       whole folder, only for Building Architect
  bacustom/       whole folder, only for Building Architect
  sc3u.ini  snapshot.ini  hotkeys.txt  icon.xpm
  sys/us/sys.pak  copy it to  sys/sys.pak   (US English)
  sys/eu/sys.pak  copy it to  sys/sys.pak   (all other languages)

Do not copy bin/ or setup.data/: the installer already provides the updated 2.0a program.
Then open SC3U Linux Installer and choose Add game files, Check copied files."""
