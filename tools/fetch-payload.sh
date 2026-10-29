#!/bin/sh
# Maintainer tool, build time only: extracts the three payload files into payload/ from the
# liflg 2.0a multilingual .mojo.run (a zip appended to an ELF). Never used at install time.
set -e; D="$(cd "$(dirname "$0")/.." && pwd)"; RUN="$1"; [ -f "$RUN" ] || { echo "usage: $0 sc3u_2.0a-multilingual_x86.mojo.run"; exit 1; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$RUN" "$T"
mkdir -p "$D/payload"; cp "$T/data/patch-2.0a.tar" "$T/data/loki_compat_libs-1_3.tar.bz2" "$T/data/spanish-patch-2.0a.tar" "$D/payload/"
(cd "$D/payload" && sha256sum *.tar* > SHA256SUMS); echo "payload ready"
