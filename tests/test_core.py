# SPDX-License-Identifier: GPL-3.0-or-later
import io, os, subprocess, sys, tarfile, tempfile, unittest, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from sc3u_installer import core

def touch(p, data=b"x"):
    os.makedirs(os.path.dirname(p), exist_ok=True); 
    with open(p, "wb") as f: f.write(data)

def fake_disc(d, kind="disc"):
    for f in ["buildings/b1.dat", "cities/c.sc3", "res/ui/u.dat", "res/sound/s.wav", "res/text/english/t.ixf",
              "res/text/german/t.ixf", "res/text/spanish/t.ixf", "res/ba/ui/x.dat", "res/ui/shared/movies/intro.mpg",
              "plugin/p", "barender/r", "bacustom/c", "sc3u.ini", "snapshot.ini", "icon.xpm"]:
        touch(os.path.join(d, f))
    os.makedirs(os.path.join(d, "res/sound/radio/stations"))
    if kind == "disc":
        touch(os.path.join(d, "bin/x86/glibc-2.1/sc3u")); touch(os.path.join(d, "bin/x86/glibc-2.1/sc3bat"))
        touch(os.path.join(d, "sys/us/sys.pak"), b"US"); touch(os.path.join(d, "sys/eu/sys.pak"), b"EU"); touch(os.path.join(d, "setup.sh"))
    else: touch(os.path.join(d, "sys/sys.pak"), b"US")

def fake_share(d):
    pay = os.path.join(d, "payload"); os.makedirs(pay)
    def mk(name, files, mode="w"):
        with tarfile.open(os.path.join(pay, name), mode) as t:
            for n, b in files.items():
                ti = tarfile.TarInfo(n); ti.size = len(b); t.addfile(ti, io.BytesIO(b))
    mk("patch-2.0a.tar", {"sc3u": b"#!/bin/sh\n", "sc3bat": b"#!/bin/sh\n", "lib/libSimCity.so": b"PATCHED"})
    mk("loki_compat_libs-1_3.tar.bz2", {"Loki_Compat/ld-linux.so.2": b"LD"}, "w:bz2")
    mk("spanish-patch-2.0a.tar", {"res/text/spanish/t.ixf": b"FIXED"})
    shutil.copytree(os.path.join(ROOT, "data"), os.path.join(d, "data")); return d

class Validation(unittest.TestCase):
    def test_disc_listing(self):
        ok, why, kind = core.validate_listing({"/bin/x86/glibc-2.1/sc3u", "/sys/us/sys.pak", "/res"}); self.assertTrue(ok); self.assertEqual(kind, "disc")
    def test_windows_rejected(self):
        ok, why, _ = core.validate_listing({"/autorun.inf", "/setup.exe", "/res"}); self.assertFalse(ok); self.assertIn("Windows", why)
    def test_random_rejected(self):
        self.assertFalse(core.validate_listing({"/foo"})[0])
    def test_game_layout_folder(self):
        with tempfile.TemporaryDirectory() as t:
            fake_disc(t, "game"); ok, _, kind = core.validate_source(t); self.assertTrue(ok); self.assertEqual(kind, "game")
    def test_disc_folder(self):
        with tempfile.TemporaryDirectory() as t:
            fake_disc(t); self.assertEqual(core.validate_source(t)[2], "disc")
    def test_non_iso_file(self):
        with tempfile.NamedTemporaryFile(suffix=".iso") as f:
            f.write(b"nope" * 100); f.flush(); self.assertFalse(core.validate_source(f.name)[0])

class Planning(unittest.TestCase):
    def test_runtime_only(self):
        s = core.plan({"with_data": False}); self.assertIn("runtime", s); self.assertNotIn("copy_data", s)
    def test_with_data_order(self):
        s = core.plan({"with_data": True, "lang": "es", "intro": False}, "disc")
        self.assertLess(s.index("copy_data"), s.index("patch_2_0a_again")); self.assertLess(s.index("patch_2_0a_again"), s.index("spanish_fix"))
        self.assertIn("drop_intro", s); self.assertEqual(s[-1], "manifest")

class InstallFlows(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(); self.home = os.path.join(self.t, "home"); os.makedirs(self.home)
        self.share = fake_share(os.path.join(self.t, "share")); self.p = core.paths(self.home); self.q = lambda *a: None
    def tearDown(self): shutil.rmtree(self.t)
    def env(self):
        e = dict(os.environ, HOME=self.home, SC3U_CHECK_ONLY="1", PATH="/usr/bin:/bin"); e.pop("XDG_DATA_HOME", None); return e
    def launcher_rc(self):
        return subprocess.run([os.path.join(self.p["bin"], "sc3u")], env=self.env(), capture_output=True, text=True)

    def test_without_iso_then_add_from_disc(self):
        o = {"lang": "de", "bat": True, "intro": False}
        core.install_runtime(o, self.home, self.share, self.q)
        self.assertEqual(core.install_state(self.home)[0], "runtime_only")
        self.assertIn("sys/sys.pak", core.missing_game_data(self.p["game"], "de"))
        r = self.launcher_rc(); self.assertEqual(r.returncode, 3); self.assertIn("missing", r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.p["apps"], "sc3u-linux-sc3u.desktop")))
        disc = os.path.join(self.t, "disc"); fake_disc(disc)
        core.add_game_data(disc, o, self.home, self.share, self.q)
        g = self.p["game"]
        self.assertEqual(core.install_state(self.home)[0], "complete")
        self.assertEqual(open(os.path.join(g, "sys/sys.pak"), "rb").read(), b"EU")
        self.assertTrue(os.path.isdir(os.path.join(g, "res/text/german"))); self.assertFalse(os.path.exists(os.path.join(g, "res/text/english")))
        self.assertFalse(os.path.exists(os.path.join(g, core.INTRO))); self.assertFalse(os.path.exists(os.path.join(g, "bin")))
        self.assertTrue(os.path.isdir(os.path.join(g, "res/sound/radio/stations")))
        self.assertEqual(open(os.path.join(g, "lib/libSimCity.so"), "rb").read(), b"PATCHED")
        self.assertEqual(self.launcher_rc().returncode, 0)

    def test_spanish_fix_applied_after_data(self):
        o = {"lang": "es"}; disc = os.path.join(self.t, "disc"); fake_disc(disc)
        core.install_runtime(o, self.home, self.share, self.q); core.add_game_data(disc, o, self.home, self.share, self.q)
        self.assertEqual(open(os.path.join(self.p["game"], "res/text/spanish/t.ixf"), "rb").read(), b"FIXED")

    def test_files_copied_in_place(self):
        o = {"lang": "en"}; core.install_runtime(o, self.home, self.share, self.q)
        src = os.path.join(self.t, "disc"); fake_disc(src)
        g = self.p["game"]
        for n in ("buildings", "cities", "res", "plugin", "sys", "sc3u.ini"):
            s = os.path.join(src, n); (shutil.copytree(s, os.path.join(g, n), dirs_exist_ok=True) if os.path.isdir(s) else shutil.copy(s, g))
        self.assertIn("sys/sys.pak", core.missing_game_data(g, "en"))   # only sys/us/sys.pak copied so far
        core.add_game_data(g, o, self.home, self.share, self.q)
        self.assertEqual(core.install_state(self.home)[0], "complete")
        self.assertEqual(open(os.path.join(g, "lib/libSimCity.so"), "rb").read(), b"PATCHED")

    def test_add_rejects_bad_source(self):
        bad = os.path.join(self.t, "bad"); os.makedirs(bad); touch(os.path.join(bad, "x"))
        with self.assertRaises(core.SourceError): core.add_game_data(bad, {}, self.home, self.share, self.q)

    def test_uninstall_keeps_saves(self):
        core.install_runtime({}, self.home, self.share, self.q); touch(os.path.join(self.home, ".loki/sc3u/cities/my.sc3"))
        core.uninstall(self.home, log=self.q)
        self.assertFalse(os.path.exists(self.p["game"])); self.assertFalse(os.path.lexists(os.path.join(self.p["bin"], "sc3u")))
        self.assertTrue(os.path.exists(os.path.join(self.home, ".loki/sc3u/cities/my.sc3")))

    def test_uninstall_refuses_foreign_folder(self):
        touch(os.path.join(self.p["game"], "something"))
        with self.assertRaises(RuntimeError): core.uninstall(self.home, log=self.q)

class RealPayload(unittest.TestCase):
    @unittest.skipUnless(os.path.isfile(os.path.join(ROOT, "payload/patch-2.0a.tar")), "payload not present")
    def test_runtime_install_real_payload(self):
        with tempfile.TemporaryDirectory() as t:
            core.install_runtime({}, t, ROOT, lambda *a: None); g = core.paths(t)["game"]
            for f in ("Loki_Compat/ld-linux.so.2", "sc3u", "sc3bat", "lib/libSimCity.so", "sc3u-launch"): self.assertTrue(os.path.lexists(os.path.join(g, f)), f)

if __name__ == "__main__": unittest.main()
