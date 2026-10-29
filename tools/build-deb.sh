#!/bin/sh
# Build sc3u-linux-installer_<ver>_all.deb unprivileged. Usage: tools/build-deb.sh [outdir]
set -e
D="$(cd "$(dirname "$0")/.." && pwd)"; OUT="${1:-$D/dist}"
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$D/src/sc3u_installer/__init__.py")
for f in patch-2.0a.tar loki_compat_libs-1_3.tar.bz2 spanish-patch-2.0a.tar; do [ -f "$D/payload/$f" ] || { echo "missing payload/$f (see tools/fetch-payload.sh)"; exit 1; }; done
R=$(mktemp -d); trap 'rm -rf "$R"' EXIT
S="$R/usr/share/sc3u-linux-installer"; mkdir -p "$S" "$R/usr/bin" "$R/usr/share/applications" "$R/usr/share/metainfo" \
  "$R/usr/share/icons/hicolor/scalable/apps" "$R/usr/share/doc/sc3u-linux-installer" "$R/DEBIAN"
cp -r "$D/src" "$D/data" "$D/payload" "$S/"; find "$S" -name __pycache__ -prune -exec rm -rf {} +
cat > "$R/usr/bin/sc3u-linux-installer" <<'W'
#!/bin/sh
export SC3U_INSTALLER_SHARE=/usr/share/sc3u-linux-installer
PYTHONPATH=/usr/share/sc3u-linux-installer/src exec python3 -m sc3u_installer "$@"
W
chmod 755 "$R/usr/bin/sc3u-linux-installer"
cp "$D/data/io.github.sc3u_linux_installer.desktop" "$R/usr/share/applications/"
cp "$D/data/io.github.sc3u_linux_installer.metainfo.xml" "$R/usr/share/metainfo/"
cp "$D/data/sc3u-installer.svg" "$R/usr/share/icons/hicolor/scalable/apps/io.github.sc3u_linux_installer.svg"
cp "$D/README.md" "$D/NOTICE" "$R/usr/share/doc/sc3u-linux-installer/"
SZ=$(du -sk "$R" | cut -f1)
cat > "$R/DEBIAN/control" <<C
Package: sc3u-linux-installer
Version: $VER
Architecture: all
Maintainer: Old Growth Crypto <315986681+OldGrowthCrypto@users.noreply.github.com>
Installed-Size: $SZ
Section: games
Priority: optional
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, genisoimage
Recommends: gir1.2-adw-1, udisks2, policykit-1 | polkitd, zenity, libnotify-bin, gamescope
Suggests: osspd, osspd-pulseaudio, gamemode
Description: Installer for the Linux edition of SimCity 3000 Unlimited
 GTK installer that builds a per user install of the native Loki Linux edition of
 SimCity 3000 Unlimited from the user's own disc or ISO, with the 2.0a update, a
 compatibility runtime, launcher and sound setup through osspd. Game data is not
 included. Unofficial, not affiliated with the game's publishers.
C
mkdir -p "$OUT"; dpkg-deb --root-owner-group -Zxz --build "$R" "$OUT/sc3u-linux-installer_${VER}_all.deb"
