#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_svg="${repo_root}/frontend/build/icon.svg"
output_png="${repo_root}/frontend/build/icon.png"
output_icns="${repo_root}/frontend/build/icon.icns"
tray_svg="${repo_root}/frontend/electron/assets/trayTemplate.svg"
tray_png="${repo_root}/frontend/electron/assets/trayTemplate.png"
tray_retina_png="${repo_root}/frontend/electron/assets/trayTemplate@2x.png"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/knowledgehub-icon.XXXXXX")"
iconset_dir="${work_dir}/KnowledgeHub.iconset"

cleanup() {
  rm -rf "${work_dir}"
}
trap cleanup EXIT

mkdir -p "${iconset_dir}"

# Electron already belongs to the desktop build toolchain, so icon generation
# does not add another SVG rasterizer or platform dependency.
raw_render="${work_dir}/icon-render.png"
(
  cd "${repo_root}/frontend"
  ./node_modules/.bin/electron \
    scripts/render-app-icon.cjs \
    "${source_svg}" \
    "${raw_render}" \
    1024
)
if [[ ! -f "${raw_render}" ]]; then
  echo "Unable to rasterize ${source_svg}" >&2
  exit 1
fi
sips -z 1024 1024 "${raw_render}" --out "${output_png}" >/dev/null
rendered_png="${output_png}"

for size in 16 32 128 256 512; do
  sips -z "${size}" "${size}" "${rendered_png}" --out "${iconset_dir}/icon_${size}x${size}.png" >/dev/null
  retina_size=$((size * 2))
  sips -z "${retina_size}" "${retina_size}" "${rendered_png}" --out "${iconset_dir}/icon_${size}x${size}@2x.png" >/dev/null
done

generated_icns="${work_dir}/icon.icns"
iconutil -c icns "${iconset_dir}" -o "${generated_icns}"
mv "${generated_icns}" "${output_icns}"

raw_tray_render="${work_dir}/tray-render.png"
(
  cd "${repo_root}/frontend"
  ./node_modules/.bin/electron \
    scripts/render-app-icon.cjs \
    "${tray_svg}" \
    "${raw_tray_render}" \
    36
)
if [[ ! -f "${raw_tray_render}" ]]; then
  echo "Unable to rasterize ${tray_svg}" >&2
  exit 1
fi
sips -z 36 36 "${raw_tray_render}" --out "${tray_retina_png}" >/dev/null
sips -z 18 18 "${raw_tray_render}" --out "${tray_png}" >/dev/null

echo "Built ${output_icns}"
