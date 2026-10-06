"""ZIP extraction regressions: index reuse, invalidation and exact filenames."""

import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


class ZipCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-zip-cache-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.archive = self.base / "archive with spaces.zip"
        self.cache = self.base / "index"
        self.cache.touch(mode=0o600)
        self.log = self.base / "unzip.log"
        self.unzip = shutil.which("unzip")
        self.assertIsNotNone(self.unzip)
        wrapper = self.base / "logged-unzip"
        wrapper.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "fd = os.open(os.environ['MC_ZIP_LOG'], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)\n"
            "os.write(fd, (json.dumps(sys.argv[1:]) + '\\n').encode())\n"
            "os.close(fd)\n"
            f"os.execv({self.unzip!r}, [{self.unzip!r}, *sys.argv[1:]])\n"
        )
        wrapper.chmod(0o700)
        if "MC_TEST_UZIP" in os.environ:
            self.helper = Path(os.environ["MC_TEST_UZIP"])
        else:
            source = Path(__file__).resolve().parents[2] / "src/vfs/extfs/helpers/uzip.in"
            text = source.read_text()
            for key, value in {"@PERL@": shutil.which("perl"), "@ZIP@": shutil.which("zip"),
                               "@UNZIP@": self.unzip, "@HAVE_ZIPINFO@": "1"}.items():
                text = text.replace(key, value)
            self.helper = self.base / "uzip"
            self.helper.write_text(text)
            self.helper.chmod(0o700)
        self.env = dict(os.environ, MC_EXTFS_CACHE=str(self.cache),
                        MC_TEST_EXTFS_LIST_CMD=str(wrapper), MC_ZIP_LOG=str(self.log),
                        LC_ALL="C.UTF-8")

    def archive_files(self, files):
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, contents in files.items():
                archive.writestr(name, contents)

    def copyout(self, name, expected, env=None):
        with tempfile.NamedTemporaryFile(dir=self.base) as out:
            subprocess.run([str(self.helper), "copyout", str(self.archive), name, out.name],
                           env=env or self.env, check=True, capture_output=True, timeout=20)
            self.assertEqual(Path(out.name).read_bytes(), expected)

    def listings(self):
        if not self.log.exists():
            return []
        return [args for line in self.log.read_text().splitlines()
                if (args := json.loads(line))[0] != "-p"]

    def test_reuses_index_across_helper_processes(self):
        files = {f"file-{i}.txt": f"contents {i}".encode() for i in range(30)}
        self.archive_files(files)
        for name, data in files.items():
            self.copyout(name, data)
        self.assertEqual(len(self.listings()), 1)

    def test_original_names_and_glob_characters(self):
        files = {
            "./space name.txt": b"spaces", "../parent.txt": b"parent",
            "a//b.txt": b"slashes", "./wild[*?].txt": b"wildcards",
            "./quote'\";$(literal).txt": b"shell metacharacters",
            "./back\\slash.txt": b"backslash",
            "./a/../inside.txt": b"middle component",
            "plain.txt": b"plain",
        }
        self.archive_files(files)
        names = ["space name.txt", "parent.txt", "a/b.txt", "wild[*?].txt",
                 "quote'\";$(literal).txt", "back\\slash.txt",
                 "a/../inside.txt", "plain.txt"]
        for name, data in zip(names, files.values()):
            self.copyout(name, data)
        self.assertEqual(len(self.listings()), 1)

    def test_long_original_name_spans_sdbm_pages(self):
        name = "./" + "/".join(["segment" * 20] * 12) + "/file.txt"
        self.archive_files({name: b"long name"})
        for _ in range(2):
            self.copyout(name[2:], b"long name")
        self.assertEqual(len(self.listings()), 1)

    def test_native_zip_utf8_filename(self):
        name = "caf\u00e9.txt"
        (self.base / name).write_bytes(b"utf8")
        subprocess.run(["zip", "-q", str(self.archive), name], cwd=self.base,
                       env=self.env, check=True, capture_output=True, timeout=20)
        for _ in range(2):
            self.copyout(name, b"utf8")
        self.assertEqual(len(self.listings()), 1)

    def test_last_canonical_name_wins(self):
        self.archive_files({"./same.txt": b"first", "same.txt": b"second"})
        for _ in range(2):
            self.copyout("same.txt", b"second")
        self.assertEqual(len(self.listings()), 1)

    def test_invalidation_after_same_size_archive_rewrite(self):
        self.archive_files({"./old.txt": b"old"})
        self.copyout("old.txt", b"old")
        before = self.archive.stat()
        self.archive_files({"./new.txt": b"new"})
        self.assertEqual(self.archive.stat().st_size, before.st_size)
        os.utime(self.archive, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.copyout("new.txt", b"new")
        self.assertEqual(len(self.listings()), 2)

    def test_invalidation_after_copyin_and_remove(self):
        self.archive_files({"./one.txt": b"one"})
        self.copyout("one.txt", b"one")
        source = self.base / "new-file"
        source.write_bytes(b"two")
        subprocess.run([str(self.helper), "copyin", str(self.archive), "two.txt", str(source)],
                       env=self.env, check=True, capture_output=True, timeout=20)
        self.copyout("two.txt", b"two")
        subprocess.run([str(self.helper), "rm", str(self.archive), "two.txt"],
                       env=self.env, check=True, capture_output=True, timeout=20)
        self.copyout("one.txt", b"one")
        self.assertEqual(len(self.listings()), 3)

    def test_concurrent_readers_share_one_complete_index(self):
        files = {f"./file-{i}.txt": f"{i}".encode() for i in range(12)}
        self.archive_files(files)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda item: self.copyout(item[0][2:], item[1]), files.items()))
        self.assertEqual(len(self.listings()), 1)

    def test_fallback_without_cache_and_with_unsafe_cache(self):
        self.archive_files({"./file.txt": b"contents"})
        for mode in ("absent", "public-parent", "symlink-lock", "symlink-index"):
            with self.subTest(mode=mode):
                env = self.env.copy()
                if mode == "absent":
                    env.pop("MC_EXTFS_CACHE")
                elif mode == "public-parent":
                    self.base.chmod(0o755)
                elif mode == "symlink-lock":
                    self.cache.unlink()
                    self.cache.symlink_to(self.base / "missing")
                else:
                    self.cache.unlink()
                    self.cache.touch(mode=0o600)
                    Path(str(self.cache) + ".pag").symlink_to(self.base / "missing")
                for _ in range(2):
                    self.copyout("file.txt", b"contents", env)
                self.base.chmod(0o700)
        self.assertEqual(len(self.listings()), 8)

    def test_without_zipinfo(self):
        self.archive_files({"./file.txt": b"contents"})
        env = dict(self.env, MC_TEST_EXTFS_HAVE_ZIPINFO="0")
        for _ in range(2):
            self.copyout("file.txt", b"contents", env)
        self.assertEqual(len(self.listings()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
