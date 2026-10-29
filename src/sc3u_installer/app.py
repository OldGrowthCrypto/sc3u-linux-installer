# SC3U Linux Installer: GTK4 / libadwaita front end. SPDX-License-Identifier: GPL-3.0-or-later
import os, sys, threading, subprocess
import gi
gi.require_version("Gtk", "4.0")
try: gi.require_version("Adw", "1"); from gi.repository import Adw
except (ValueError, ImportError): Adw = None
from gi.repository import Gtk, GLib, Gio
from . import core, __version__, APP_ID

def label(text, css=None, wrap=True, xalign=0.5, sel=False):
    l = Gtk.Label(label=text, wrap=wrap, xalign=xalign, justify=Gtk.Justification.CENTER if xalign == 0.5 else Gtk.Justification.LEFT)
    l.set_selectable(sel)
    if css: l.add_css_class(css)
    return l

def button(text, cb, css=None):
    b = Gtk.Button(label=text); b.connect("clicked", cb)
    if css: b.add_css_class(css)
    b.add_css_class("pill"); b.set_halign(Gtk.Align.CENTER); return b

def page_box():
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=28, margin_bottom=28, margin_start=36, margin_end=36)
    b.set_valign(Gtk.Align.CENTER); return b

class Win(Gtk.ApplicationWindow if Adw is None else Adw.ApplicationWindow):
    def __init__(self, app, start=None):
        super().__init__(application=app, title="SC3U Linux Installer", default_width=720, default_height=600)
        self.opts = {"lang": "en", "bat": True, "intro": True, "fullscreen": True, "resolution": "auto", "stretch": False, "with_data": True}
        self.source = None; self.mode = "install"  # install | add
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        hb = (Adw.HeaderBar() if Adw else Gtk.HeaderBar())
        menu = Gio.Menu(); menu.append("Add game files", "win.add"); menu.append("Show which files to copy", "win.manual")
        menu.append("Sound check", "win.sound"); menu.append("Uninstall", "win.uninstall"); menu.append("About", "win.about")
        mb = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu); hb.pack_end(mb)
        for name, cb in (("add", lambda *a: self.start_add()), ("manual", lambda *a: self.go("manual")),
                         ("sound", lambda *a: self.go_sound()), ("uninstall", lambda *a: self.go("uninstall")), ("about", self.about)):
            act = Gio.SimpleAction.new(name, None); act.connect("activate", cb); self.add_action(act)
        if Adw:
            tv = Adw.ToolbarView(); tv.add_top_bar(hb); tv.set_content(self.stack); self.set_content(tv)
        else:
            self.set_titlebar(hb); self.set_child(self.stack)
        for n in ("welcome", "source", "options", "progress", "sound", "done", "manual", "uninstall"):
            getattr(self, "build_" + n)()
        self.refresh_welcome()
        if start == "add": self.start_add()
        elif start: self.go(start)

    def go(self, name): self.stack.set_visible_child_name(name)

    # ---------- welcome
    def build_welcome(self):
        b = page_box(); pic = Gtk.Picture.new_for_filename(os.path.join(core.share_dir(), "data/banner.jpg"))
        pic.set_content_fit(Gtk.ContentFit.CONTAIN); pic.set_can_shrink(True); pic.set_size_request(-1, 180)
        b.append(pic); b.append(label("SC3U Linux Installer", "title-1"))
        b.append(label("Installs the native Linux edition of SimCity 3000 Unlimited on modern Ubuntu, with the 2.0a update, "
                       "a compatibility runtime and working sound.\n\nYou need your own copy of the Loki Linux edition disc "
                       "or its ISO. No game data is included with this installer.", "body"))
        self.w_state = label("", "dim-label"); b.append(self.w_state)
        b.append(button("Install with my ISO or disc", lambda *_: self.start_install(True), "suggested-action"))
        b.append(button("Install without ISO, add game files later", lambda *_: self.start_install(False)))
        self.w_add = button("Add game files", lambda *_: self.start_add()); b.append(self.w_add)
        self.w_play = button("Launch game", self.launch, "suggested-action"); b.append(self.w_play)
        self.stack.add_named(b, "welcome")

    def refresh_welcome(self):
        st, p, m = core.install_state()
        self.w_state.set_text({"none": "Not installed yet.", "runtime_only": "Installed without game files. Add them to play.",
                               "complete": "Installed and ready to play."}[st])
        self.w_add.set_visible(st != "complete"); self.w_play.set_visible(st == "complete")
        if m: self.opts.update({k: m[k] for k in ("lang", "bat", "intro", "fullscreen", "resolution", "stretch") if k in m})

    def start_install(self, with_data):
        self.mode = "install"; self.opts["with_data"] = with_data; self.source = None
        if with_data: self.prepare_source(); self.go("source")
        else: self.go("options")

    def start_add(self):
        self.mode = "add"; self.opts["with_data"] = True; self.source = None; self.prepare_source(); self.go("source")

    # ---------- source
    def build_source(self):
        b = page_box(); self.s_title = label("Choose your game disc", "title-2"); b.append(self.s_title)
        b.append(label("Pick the ISO file, the mounted disc, or a folder with the copied disc files.", "body"))
        row = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        row.append(button("Choose ISO file", self.pick_iso, "suggested-action")); row.append(button("Choose disc or folder", self.pick_dir))
        b.append(row)
        self.s_check = button("Check files copied into the game folder", self.use_inplace); b.append(self.s_check)
        self.s_path = label("", "monospace", sel=True); b.append(self.s_path)
        self.s_result = label(""); b.append(self.s_result)
        nav = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        nav.append(button("Back", lambda *_: (self.refresh_welcome(), self.go("welcome"))))
        self.s_next = button("Next", lambda *_: self.go("options"), "suggested-action"); self.s_next.set_sensitive(False); nav.append(self.s_next)
        b.append(nav); self.stack.add_named(b, "source")

    def prepare_source(self):
        self.s_title.set_text("Add game files" if self.mode == "add" else "Choose your game disc")
        self.s_check.set_visible(self.mode == "add"); self.s_path.set_text(""); self.s_result.set_text(""); self.s_next.set_sensitive(False)

    def pick_iso(self, *_):
        d = Gtk.FileDialog(title="Choose the SC3U Linux ISO"); f = Gtk.FileFilter(); f.set_name("Disc images"); f.add_pattern("*.iso"); f.add_pattern("*.ISO")
        fl = Gio.ListStore.new(Gtk.FileFilter); fl.append(f); d.set_filters(fl)
        d.open(self, None, lambda dlg, res: self._picked(dlg.open_finish(res)) if not self._cancel(dlg.open_finish, res) else None)

    def pick_dir(self, *_):
        d = Gtk.FileDialog(title="Choose the disc or folder")
        d.select_folder(self, None, lambda dlg, res: self._picked(dlg.select_folder_finish(res)) if not self._cancel(dlg.select_folder_finish, res) else None)

    def _cancel(self, fn, res):
        try: self._last = fn(res); return False
        except GLib.Error: return True

    def _picked(self, gfile): self.set_source(gfile.get_path())

    def use_inplace(self, *_): self.set_source(core.paths()["game"], inplace=True)

    def set_source(self, path, inplace=False):
        self.source = path; self.s_path.set_text(path); self.s_result.set_text("Checking...")
        def work():
            if inplace:
                miss = core.missing_game_data(path, self.opts["lang"]); ok = not [m for m in miss if not m.startswith("res/text")]
                why = "Copied files found" if ok else "Still missing: " + ", ".join(miss)
            else: ok, why, _ = core.validate_source(path)
            GLib.idle_add(self._validated, ok, why)
        threading.Thread(target=work, daemon=True).start()

    def _validated(self, ok, why):
        self.s_result.set_text(("✓ " if ok else "✗ ") + why); self.s_result.remove_css_class("success" if not ok else "error")
        self.s_result.add_css_class("success" if ok else "error"); self.s_next.set_sensitive(ok)

    # ---------- options
    def build_options(self):
        b = page_box(); b.append(label("Options", "title-2"))
        grid = Gtk.Grid(column_spacing=14, row_spacing=12, halign=Gtk.Align.CENTER)
        grid.attach(label("Language", xalign=0), 0, 0, 1, 1)
        self.o_lang = Gtk.DropDown.new_from_strings([v[0] for v in core.LANGS.values()]); grid.attach(self.o_lang, 1, 0, 1, 1)
        self.o_bat = Gtk.Switch(active=True, halign=Gtk.Align.START); grid.attach(label("Building Architect Tool", xalign=0), 0, 1, 1, 1); grid.attach(self.o_bat, 1, 1, 1, 1)
        self.o_intro = Gtk.Switch(active=False, halign=Gtk.Align.START); grid.attach(label("Skip the intro movie", xalign=0), 0, 2, 1, 1); grid.attach(self.o_intro, 1, 2, 1, 1)
        self.o_fs = Gtk.Switch(active=True, halign=Gtk.Align.START); grid.attach(label("Fullscreen", xalign=0), 0, 3, 1, 1); grid.attach(self.o_fs, 1, 3, 1, 1)
        self.RES = ["auto", "1280x1024", "1024x768", "800x600"]; self.o_res = Gtk.DropDown.new_from_strings(["Auto (best: 1280x1024)", "1280x1024", "1024x768", "800x600"]); grid.attach(label("Resolution", xalign=0), 0, 4, 1, 1); grid.attach(self.o_res, 1, 4, 1, 1)
        self.o_st = Gtk.Switch(active=False, halign=Gtk.Align.START); grid.attach(label("Stretch to fill", xalign=0), 0, 5, 1, 1); grid.attach(self.o_st, 1, 5, 1, 1)
        b.append(grid)
        b.append(label("Installs into your home folder (~/.local/share/sc3u-linux). Saved cities stay in ~/.loki/sc3u.", "dim-label"))
        nav = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        nav.append(button("Back", lambda *_: self.go("source" if self.opts["with_data"] else "welcome")))
        nav.append(button("Install", self.run_install, "suggested-action")); b.append(nav)
        self.stack.add_named(b, "options")

    # ---------- progress
    def build_progress(self):
        b = page_box(); b.set_valign(Gtk.Align.FILL); self.p_title = label("Installing", "title-2"); b.append(self.p_title)
        self.p_bar = Gtk.ProgressBar(show_text=True); b.append(self.p_bar)
        self.p_buf = Gtk.TextBuffer(); tv = Gtk.TextView(buffer=self.p_buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        sw = Gtk.ScrolledWindow(vexpand=True, min_content_height=240); sw.set_child(tv); b.append(sw)
        self.p_next = button("Continue", lambda *_: self.go_sound(), "suggested-action"); self.p_next.set_sensitive(False); b.append(self.p_next)
        self.stack.add_named(b, "progress")

    def log(self, msg): GLib.idle_add(lambda: (self.p_buf.insert(self.p_buf.get_end_iter(), msg + "\n"), False)[1])
    def prog(self, f, text=None): GLib.idle_add(lambda: (self.p_bar.set_fraction(f), self.p_bar.set_text(text or "%d%%" % (f * 100)), False)[2])

    def run_install(self, *_):
        keys = list(core.LANGS); self.opts.update(lang=keys[self.o_lang.get_selected()], bat=self.o_bat.get_active(), intro=not self.o_intro.get_active(), fullscreen=self.o_fs.get_active(), resolution=self.RES[self.o_res.get_selected()], stretch=self.o_st.get_active())
        self.p_buf.set_text(""); self.p_next.set_sensitive(False); self.go("progress")
        self.p_title.set_text("Adding game files" if self.mode == "add" else "Installing")
        def work():
            try:
                if not core.free_space_ok(need_mb=1200 if self.opts["with_data"] else 80): raise RuntimeError("Not enough free disk space in your home folder.")
                if self.mode == "install":
                    self.prog(0.05, "Runtime"); core.install_runtime(self.opts, log=self.log)
                if self.opts["with_data"]:
                    self.prog(0.15, "Game files")
                    core.add_game_data(self.source, self.opts, log=self.log, progress=lambda f: self.prog(0.15 + 0.8 * f))
                self.prog(1.0, "Done"); self.log("Finished."); ok = True
            except Exception as e:
                self.log("ERROR: %s" % e); self.prog(0, "Failed"); ok = False
            GLib.idle_add(lambda: (self.p_next.set_sensitive(ok), False)[1])
        threading.Thread(target=work, daemon=True).start()

    # ---------- sound
    def build_sound(self):
        b = page_box(); b.append(label("Sound check", "title-2"))
        b.append(label("The game plays sound through /dev/dsp. On modern Ubuntu that is provided by osspd, which forwards it to PipeWire.", "body"))
        self.so_state = label(""); b.append(self.so_state)
        self.so_fix = button("Fix sound (asks for your password)", self.fix_sound, "suggested-action"); b.append(self.so_fix)
        b.append(button("Continue", lambda *_: self.go_done(), None)); self.stack.add_named(b, "sound")

    def go_sound(self):
        s = core.sound_status()
        self.so_state.set_text("✓ /dev/dsp is ready, sound will work." if s["ok"] else
                               "✗ /dev/dsp is missing. osspd is %s." % ("installed but not running" if s["osspd_installed"] else "not installed"))
        self.so_fix.set_visible(not s["ok"]); self.go("sound")

    def fix_sound(self, *_):
        self.so_state.set_text("Working...")
        def work():
            r = subprocess.run(core.sound_fix_cmd(), capture_output=True, text=True)
            GLib.idle_add(lambda: (self.go_sound(), r.returncode and self.so_state.set_text("The fix did not finish: " + (r.stderr.strip()[-200:] or "cancelled")), False)[2])
        threading.Thread(target=work, daemon=True).start()

    # ---------- done
    def build_done(self):
        b = page_box(); self.d_title = label("All set", "title-1"); b.append(self.d_title); self.d_text = label("", "body"); b.append(self.d_text)
        self.d_play = button("Launch", self.launch, "suggested-action"); b.append(self.d_play)
        self.d_add = button("Show which files to copy", lambda *_: self.go("manual")); b.append(self.d_add)
        b.append(button("Close", lambda *_: self.close())); self.stack.add_named(b, "done")

    def go_done(self):
        st, p, _ = core.install_state()
        if st == "complete":
            self.d_title.set_text("All set"); self.d_text.set_text("Find SC3U (Linux) in your app grid, or run sc3u in a terminal.")
        else:
            self.d_title.set_text("Runtime installed"); self.d_text.set_text("The game files are not added yet. Copy them later and choose Add game files from the menu, or simply start the game and it will bring you back here.")
        self.d_play.set_visible(st == "complete"); self.d_add.set_visible(st != "complete"); self.go("done")

    def launch(self, *_):
        subprocess.Popen([os.path.join(core.paths()["game"], "sc3u-launch")], start_new_session=True)

    # ---------- manual copy
    def build_manual(self):
        b = page_box(); b.append(label("Which files to copy", "title-2"))
        b.append(label(core.MANUAL_COPY.format(game=core.paths()["game"]), "monospace", xalign=0, sel=True))
        nav = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        nav.append(button("Back", lambda *_: (self.refresh_welcome(), self.go("welcome"))))
        nav.append(button("Open game folder", self.open_folder)); nav.append(button("Add game files", lambda *_: self.start_add(), "suggested-action"))
        b.append(nav); self.stack.add_named(b, "manual")

    def open_folder(self, *_):
        g = core.paths()["game"]; os.makedirs(g, exist_ok=True); Gtk.FileLauncher.new(Gio.File.new_for_path(g)).launch(self, None, None)

    # ---------- uninstall
    def build_uninstall(self):
        b = page_box(); b.append(label("Uninstall", "title-2"))
        b.append(label("Removes the game folder, the menu entries and the sc3u commands from your home folder. Your saved cities in ~/.loki/sc3u are kept. The osspd sound service is left as is.", "body"))
        self.u_res = label(""); b.append(self.u_res)
        nav = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        nav.append(button("Back", lambda *_: (self.refresh_welcome(), self.go("welcome"))))
        nav.append(button("Uninstall", self.do_uninstall, "destructive-action")); b.append(nav); self.stack.add_named(b, "uninstall")

    def do_uninstall(self, *_):
        try: core.uninstall(log=lambda m: None); self.u_res.set_text("Removed.")
        except Exception as e: self.u_res.set_text(str(e))

    def about(self, *_):
        if Adw:
            d = Adw.AboutDialog(application_name="SC3U Linux Installer", version=__version__, license_type=Gtk.License.GPL_3_0,
                                comments="Unofficial community installer. Not affiliated with the game's publishers. No game data included.")
            d.present(self)

class App(Gtk.Application if Adw is None else Adw.Application):
    def __init__(self, start=None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE); self.start = start
    def do_activate(self):
        w = Win(self, self.start); w.present()
        shots = os.environ.get("SC3U_SCREENSHOTS")
        if shots: GLib.timeout_add(1200, lambda: shoot(w, shots))

def shoot(w, outdir):
    """Test helper: render each page to PNG with the window's own renderer."""
    os.makedirs(outdir, exist_ok=True)
    seq = [("01-welcome", lambda: w.go("welcome")), ("02-source", lambda: (w.start_add() if False else w.start_install(True))),
           ("03-source-validated", lambda: w._validated(True, "Loki Linux edition of SimCity 3000 Unlimited")),
           ("04-options", lambda: w.go("options")),
           ("05-progress", lambda: (w.go("progress"), w.p_bar.set_fraction(0.42), w.p_bar.set_text("Game files"),
                                    w.p_buf.set_text("Installing compatibility runtime (Loki_Compat)\nInstalling update 2.0a (game program and libraries)\nCopying game files from /path/to/SC3U.iso\n"))),
           ("06-sound", lambda: w.go_sound()), ("07-done", lambda: w.go_done()), ("08-manual", lambda: w.go("manual")),
           ("09-add-files", lambda: w.start_add()), ("10-uninstall", lambda: w.go("uninstall"))]
    def step(i=0):
        if i > 0:
            name = seq[i - 1][0]; paint = Gtk.WidgetPaintable.new(w); W, H = w.get_width(), w.get_height()
            snap = Gtk.Snapshot(); paint.snapshot(snap, W, H); node = snap.to_node()
            if node: w.get_native().get_renderer().render_texture(node, None).save_to_png(os.path.join(outdir, name + ".png"))
        if i == len(seq): w.get_application().quit(); return False
        seq[i][1](); GLib.timeout_add(900, step, i + 1); return False
    step(); return False

def main(argv=None):
    argv = list(sys.argv if argv is None else argv); start = None
    if "--add-files" in argv: start = "add"; argv.remove("--add-files")
    for a in list(argv):
        if a.startswith("--page="): start = a.split("=", 1)[1]; argv.remove(a)
    if "--version" in argv: print(__version__); return 0
    return App(start).run(argv[:1])
