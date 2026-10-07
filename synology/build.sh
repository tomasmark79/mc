#!/usr/bin/env bash
set -euo pipefail

# Build on a Linux PC; the NAS only needs the resulting archive.
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cache=${MC_DSM_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/mc-dsm}
output=${MC_DSM_OUTPUT:-$repo/dist/synology}
mkdir -p "$cache" "$output"
cache=$(realpath "$cache")
output=$(realpath "$output")

fetch() {
    local name=$1 hash=$2 url=$3
    if ! printf '%s  %s\n' "$hash" "$cache/$name" | sha256sum --check --status 2>/dev/null; then
        curl -fL --retry 2 --output "$cache/$name.part" "$url"
        printf '%s  %s\n' "$hash" "$cache/$name.part" | sha256sum --check
        mv -- "$cache/$name.part" "$cache/$name"
    fi
}

fetch rtd1619b-gcc1220_glibc236_armv8-GPL.txz \
    cc3a5e6b0d9dc8c8cf0ef7aa3dd9f0aa02413e4e00ad3fc5143a126ff74f04f0 \
    'https://global.synologydownload.com/download/ToolChain/toolchain/7.2-63134/Realtek%20RTD16xxb%20Linux%205.10.55/rtd1619b-gcc1220_glibc236_armv8-GPL.txz'
fetch ds.rtd1619b-7.4.dev.txz \
    801b57f20cd40284b09167dfdaa72dbac838b64da3a95d386b87c6be69594181 \
    https://global.synologydownload.com/download/ToolChain/toolkit/7.4/rtd1619b/ds.rtd1619b-7.4.dev.txz

sdk=$cache/sdk-7.4-801b57f
if [[ ! -f $sdk/.complete ]]; then
    sdk_tmp=$(mktemp -d "$cache/sdk-7.4.XXXXXXXX")
    mkdir -p "$sdk_tmp/toolchain" "$sdk_tmp/dev"
    tar -xJf "$cache/rtd1619b-gcc1220_glibc236_armv8-GPL.txz" -C "$sdk_tmp/toolchain"
    tar -xJf "$cache/ds.rtd1619b-7.4.dev.txz" -C "$sdk_tmp/dev" \
        usr/local/aarch64-unknown-linux-gnu/aarch64-unknown-linux-gnu/sysroot
    compiler=$sdk_tmp/toolchain/aarch64-unknown-linux-gnu
    sysroot=$compiler/aarch64-unknown-linux-gnu/sysroot
    chmod -R u+w "$compiler"
    cp -a "$sdk_tmp/dev/usr/local/aarch64-unknown-linux-gnu/aarch64-unknown-linux-gnu/sysroot/." "$sysroot/"
    chmod -R u+w "$sysroot"
    # SDK pkg-config metadata contains paths from Synology's build host.
    python3 - "$sysroot" <<'PY'
import pathlib, sys
for pc in pathlib.Path(sys.argv[1]).rglob('*.pc'):
    text = pc.read_text()
    pc.write_text(text.replace('/usr/local/aarch64-unknown-linux-gnu/aarch64-unknown-linux-gnu/sysroot/', '/'))
PY
    rm -rf -- "${sdk_tmp:?}/dev"
    touch "$sdk_tmp/.complete"
    mv -T "$sdk_tmp" "$sdk"
fi
compiler=$sdk/toolchain/aarch64-unknown-linux-gnu
sysroot=$compiler/aarch64-unknown-linux-gnu/sysroot
export PATH="$compiler/bin:$PATH"
export CC="aarch64-unknown-linux-gnu-gcc --sysroot=$sysroot"
export AR=aarch64-unknown-linux-gnu-ar
export RANLIB=aarch64-unknown-linux-gnu-ranlib
export STRIP=aarch64-unknown-linux-gnu-strip
export PKG_CONFIG_SYSROOT_DIR="$sysroot"
export PKG_CONFIG_LIBDIR="$sysroot/usr/lib/pkgconfig:$sysroot/usr/share/pkgconfig"
unset PKG_CONFIG_PATH
export CFLAGS='-O2 -march=armv8-a'
export CPPFLAGS=
export LDFLAGS="-Wl,-rpath-link,$sysroot/usr/lib -Wl,-rpath-link,$sysroot/lib"

work=$(mktemp -d "$cache/build.XXXXXXXX")
printf 'Build directory: %s\n' "$work"
mkdir -p "$work/source" "$work/stage"
# Include current tracked source changes, without .git or generated build files.
git -C "$repo" ls-files -z | tar -C "$repo" --null -T - -cf - | tar -C "$work/source" -xf -
cd "$work/source"
patch -p1 < "$repo/synology/relocatable.patch"
./autogen.sh
./configure --build="$(./config/config.guess)" --host=aarch64-unknown-linux-gnu \
    --prefix=/usr/local/mc-modern --libexecdir=/usr/local/mc-modern/libexec \
    --sysconfdir=/usr/local/mc-modern/etc --with-screen=ncurses \
    --without-x --without-gpm-mouse --disable-aspell --disable-vfs-undelfs \
    --disable-configure-args PERL=/usr/bin/perl PERL_FOR_BUILD="$(command -v perl)" \
    ZIP=/usr/bin/zip UNZIP=/usr/bin/unzip
make -j"${MC_DSM_JOBS:-$(nproc)}"
make DESTDIR="$work/stage" install

bundle=$work/stage/usr/local/mc-modern
mv "$bundle/bin/mc" "$bundle/bin/mc.bin"
for program in mcedit mcview mcdiff; do
    ln -s mc.bin "$bundle/bin/$program.bin"
done
install -m755 "$repo/synology/mc" "$bundle/bin/mc"
"$STRIP" "$bundle/bin/mc.bin"
tic -x -o "$bundle/share/terminfo" "$repo/synology/terminfo.src"
python3 - "$bundle" <<'PY'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
ext = root / 'etc/mc/mc.ext.ini'
ext.write_text(ext.read_text().replace('/usr/local/mc-modern/libexec/mc/ext.d', '"${MC_EXTHELPERSDIR}"'))
clipboard = root / 'share/mc/mc-clipboard.menu'
clipboard.write_text(clipboard.read_text().replace('/usr/local/mc-modern', '${MC_BUNDLE_ROOT}'))
wrapper = root / 'libexec/mc/mc-wrapper.sh'
wrapper_root = 'MC_DSM_WRAPPER_ROOT=$(CDPATH=\'\' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)\n'
wrapper.write_text(wrapper_root + wrapper.read_text().replace(
    '/usr/local/mc-modern/bin/mc', '"${MC_DSM_WRAPPER_ROOT}/bin/mc"') + '\nunset MC_DSM_WRAPPER_ROOT\n')
PY
cp "$repo/synology/README.md" "$bundle/README.md"
cp "$repo/COPYING" "$bundle/COPYING"
cp "$repo/synology/COPYING.terminfo" "$bundle/COPYING.terminfo"
git -C "$repo" rev-parse HEAD > "$bundle/SOURCE_REVISION"
git -C "$repo" diff --binary HEAD > "$bundle/SOURCE_CHANGES.patch"
version=$(cat "$repo/dotname/VERSION")
archive=$output/mc-modern-$version-dsm7-rtd1619b.tar.gz
file "$bundle/bin/mc.bin"
readelf -d "$bundle/bin/mc.bin" | sed -n '/NEEDED/p; /RPATH/p; /RUNPATH/p'
tar -C "$work/stage/usr/local" -czf "$archive" mc-modern
(cd "$output" && sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256")
printf '\nArchive: %s\n' "$archive"
