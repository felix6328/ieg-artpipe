#!/usr/bin/env bash
# R1 evidence: list texture basenames that exist as both .png and .dds at a given revision.
# Usage (inside a blobless clone of 0ad): bash dupcheck.sh <rev>
# Verified 2026-11-16: `bash dupcheck.sh eafacb6e2^` prints exactly the 5 files of issue #6738;
#                      `bash dupcheck.sh HEAD` prints nothing; `0dd3bcc8e^` gives 13 groups.
set -euo pipefail
A=binaries/data/mods/public/art/textures
git ls-tree -r --name-only "${1:-HEAD}" -- "$A" | grep -Ei '\.(png|dds)$' | sed -E 's/\.(png|dds)$//I' | sort | uniq -d
