#!/bin/bash
# Packaging script for Kodi addon
# Creates a zip file ready for Kodi installation.
# Packages HEAD via git archive: what ships is exactly what is committed,
# so local build residue (__pycache__, .DS_Store, ...) can never sneak in.

set -euo pipefail

cd "$(dirname "$0")"

ADDON_ID="service.subtitles.chinesesubtitles"
VERSION=$(python3 -c "import xml.etree.ElementTree as t; print(t.parse('addon.xml').getroot().get('version') or '')")
if [[ -z "${VERSION}" ]]; then
  echo "Failed to read version from addon.xml" >&2
  exit 1
fi
OUTPUT_DIR="dist"
OUTPUT_FILE="${OUTPUT_DIR}/${ADDON_ID}-${VERSION}.zip"

echo "Packaging ${ADDON_ID} version ${VERSION}..."

# Create output directory
mkdir -p "${OUTPUT_DIR}"

# Clean previous builds
rm -f "${OUTPUT_DIR}/${ADDON_ID}"*.zip

# --prefix gives the zip the top-level folder Kodi requires
git archive --format=zip --prefix="${ADDON_ID}/" -o "${OUTPUT_FILE}" HEAD addon.xml resources

echo "Successfully created: ${OUTPUT_FILE}"
echo "File size: $(ls -lh "${OUTPUT_FILE}" | awk '{print $5}')"
