"""Regression tests for MC customizations, using temporary directories without sudo."""

import configparser
import importlib.util
import io
import os
import shutil
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest
import zipfile
from unittest.mock import MagicMock, patch


BINARY = os.environ["MC_TEST_BINARY"]
HELPER = os.environ["MC_TEST_HELPER"]


class Session:
    def __init__(self, directory, skin=None, root=False, args=(), envskin=None,
                 keymap="", truecolor=True, safe_delete=False, extra_env=None):
        self.base = Path(directory)
        self.socket = str(self.base / "tmux.sock")
        self.config = self.base / "config/mc"
        self.base.mkdir(parents=True, exist_ok=True)
        if skin is not None or keymap:
            self.config.mkdir(parents=True)
        if skin is not None:
            (self.config / "ini").write_text(
                "[Midnight-Commander]\nskin=" + skin
                + "\nconfirm_exit=false\nauto_save_setup=true\npause_after_run=0\n"
            )
        if safe_delete:
            config = self.config / "ini"
            config.write_text(config.read_text() + "safe_delete=true\n")
        if keymap:
            (self.config / "mc.keymap").write_text(keymap)
        self.left, self.right = self.base / "left", self.base / "right"
        self.left.mkdir()
        self.right.mkdir()
        self.file = self.left / "file with spaces.txt"
        self.file.write_text("test content\n")
        (self.right / "other.txt").write_text("second panel\n")
        env = os.environ.copy()
        for key in ("MC_TMPDIR", "MC_SID", "MC_SKIN", "MC_KEYMAP", "TMUX", "TMUX_PANE", "DISPLAY"):
            env.pop(key, None)
        env.update(XDG_CONFIG_HOME=str(self.base / "config"),
                   XDG_DATA_HOME=str(self.base / "data"),
                   XDG_CACHE_HOME=str(self.base / "cache"),
                   TMPDIR=str(self.base), COLORTERM="truecolor", LC_ALL="C.UTF-8")
        if not truecolor:
            env.pop("COLORTERM", None)
        # Shortcuts must not modify the actual desktop clipboard.
        runtime = self.base / "runtime"
        runtime.mkdir(mode=0o700)
        env.update(XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY=str(runtime / "missing-wayland"))
        if envskin:
            env["MC_SKIN"] = envskin
        if extra_env:
            env.update(extra_env)
        command = (["unshare", "--user", "--map-root-user", "--"] if root else [])
        command += [BINARY, "-u", *args, str(self.left), str(self.right)]
        subprocess.run(["tmux", "-f", "/dev/null", "-S", self.socket,
                        "new-session", "-d", "-s", "test", "-x", "120", "-y", "35",
                        shlex.join(command)], env=env, check=True, timeout=10,
                       capture_output=True)

    def tmux(self, *args):
        return subprocess.check_output(["tmux", "-S", self.socket, *args],
                                       text=True, stderr=subprocess.STDOUT, timeout=5)

    def screen(self):
        return self.tmux("capture-pane", "-t", "test", "-pe")

    def wait(self, predicate, description):
        deadline = time.monotonic() + 8
        last = ""
        while time.monotonic() < deadline:
            last = self.screen()
            if predicate(last):
                return last
            time.sleep(.05)
        raise AssertionError(description + "\n" + last)

    def keys(self, *keys):
        self.tmux("send-keys", "-t", "test", *keys)

    def color(self, name, root=False):
        if name == "light":
            sequence = "\x1b[48;5;" + ("161" if root else "252") + "m"
        else:
            sequence = "\x1b[48;5;" + ("52" if root else "24") + "m"
        return self.wait(lambda s: sequence in s,
                         "Expected cursor color is missing: " + name)

    def stop(self):
        subprocess.run(["tmux", "-S", self.socket, "kill-server"],
                       capture_output=True, timeout=5)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        # GIO refuses trash on some system filesystems, such as the one containing /tmp.
        self.tmp = tempfile.TemporaryDirectory(prefix=".mc-regression-", dir=Path.home())
        self.addCleanup(self.tmp.cleanup)

    def session(self, **kwargs):
        s = Session(self.tmp.name, **kwargs)
        self.addCleanup(s.stop)
        return s

    def test_zip_f5_streaming_and_cleanup(self):
        s = self.session(skin="dotname-light")
        s.file.unlink()
        archive = s.left / "many-files.zip"
        files = {f"folder/file-{i:04d}.txt": f"contents {i}\n".encode()
                 for i in range(500)}
        files["folder/space [*?].txt"] = b"special name\n"
        files["folder/empty.txt"] = b""
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, data in files.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = 0o100644 << 16
                compression = zipfile.ZIP_STORED if name.endswith("0.txt") else zipfile.ZIP_DEFLATED
                z.writestr(info, data, compress_type=compression)
        # Refresh the panel, enter the archive, and copy its directory with F5.
        s.keys("C-r")
        s.wait(lambda t: "many-files.zip" in t, "ZIP archive is missing")
        s.keys("Home", "Down", "Enter")
        s.wait(lambda t: "uzip://" in t and "folder" in t, "ZIP panel did not open")
        s.keys("Home", "Down", "F5")
        s.wait(lambda t: "source mask:" in t and "folder" in t, "Copy dialog did not open")
        s.keys("Enter")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if all((s.right / name).is_file() and (s.right / name).read_bytes() == data
                   for name, data in files.items()):
                break
            time.sleep(.1)
        for name, data in files.items():
            self.assertEqual((s.right / name).read_bytes(), data)
        s.wait(lambda t: "Source" not in t and "source mask:" not in t,
               "Copy did not finish")
        self.assertFalse(list(s.base.glob("mc-*/extfs-cache*.pag")), "F5 used the ZIP helper")
        self.assertFalse([p for p in s.base.glob("mc-*/extfs*")
                          if not p.name.startswith("extfs-cache")], "F5 extracted temporary files")
        s.keys("F10")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and list(s.base.glob("mc-*/extfs-cache*")):
            time.sleep(.05)
        self.assertFalse(list(s.base.glob("mc-*/extfs-cache*")), "ZIP index was not cleaned up")

    def zip_with_file(self, archive, contents, compression=zipfile.ZIP_DEFLATED):
        with zipfile.ZipFile(archive, "w", compression=compression) as z:
            info = zipfile.ZipInfo("file.txt")
            info.external_attr = 0o100644 << 16
            z.writestr(info, contents, compress_type=compression)

    def open_zip_panel(self, s, archive):
        s.tmux("send-keys", "-t", "test", "-l", "cd " + str(archive) + "/uzip://")
        s.keys("Enter")
        s.wait(lambda t: "uzip://" in t and "file.txt" in t, "ZIP panel did not open")

    def copy_zip_file(self, s, expected):
        s.keys("Home", "Down", "F5")
        s.wait(lambda t: "source mask:" in t, "Copy dialog did not open")
        s.keys("Enter")
        output = s.right / "file.txt"
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if output.is_file() and output.read_bytes() == expected:
                break
            time.sleep(.05)
        self.assertEqual(output.read_bytes(), expected)
        s.wait(lambda t: "Source" not in t and "source mask:" not in t, "Copy did not finish")

    def test_zip_streaming_invalidation(self):
        s = self.session(skin="dotname-light")
        archive = s.left / "changing.zip"
        self.zip_with_file(archive, b"first")
        self.open_zip_panel(s, archive)
        self.copy_zip_file(s, b"first")
        before = archive.stat()
        self.zip_with_file(archive, b"later")
        self.assertEqual(archive.stat().st_size, before.st_size)
        os.utime(archive, ns=(before.st_atime_ns, before.st_mtime_ns))
        (s.right / "file.txt").unlink()
        self.copy_zip_file(s, b"later")

    def test_zip_streaming_crc_error(self):
        s = self.session(skin="dotname-light")
        archive = s.left / "broken.zip"
        self.zip_with_file(archive, b"contents", zipfile.ZIP_STORED)
        with zipfile.ZipFile(archive) as z:
            info = z.infolist()[0]
            offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        with archive.open("r+b") as f:
            f.seek(offset)
            f.write(b"X")
        self.open_zip_panel(s, archive)
        s.keys("Home", "Down", "F5")
        s.wait(lambda t: "source mask:" in t, "Copy dialog did not open")
        s.keys("Enter")
        s.wait(lambda t: "Cannot read source file" in t, "ZIP CRC error was not reported")

    def test_zip_custom_helper_fallback(self):
        helper_dir = Path(self.tmp.name) / "data/mc/extfs.d"
        helper_dir.mkdir(parents=True)
        helper = Path(BINARY).resolve().parents[1] / "libexec/mc/extfs.d/uzip"
        shutil.copyfile(helper, helper_dir / "uzip")
        (helper_dir / "uzip").chmod(0o700)
        s = self.session(skin="dotname-light")
        archive = s.left / "custom.zip"
        self.zip_with_file(archive, b"custom helper")
        self.open_zip_panel(s, archive)
        self.copy_zip_file(s, b"custom helper")
        self.assertTrue(list(s.base.glob("mc-*/extfs-cache*.pag")), "Custom ZIP helper was bypassed")

    def test_zip_alias_fallback(self):
        s = self.session(skin="dotname-light")
        archive = s.left / "aliases.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for name, contents in (("file.txt", b"first"), ("./file.txt", b"alias")):
                info = zipfile.ZipInfo(name)
                info.external_attr = 0o100644 << 16
                z.writestr(info, contents)
        self.open_zip_panel(s, archive)
        self.copy_zip_file(s, b"alias")
        self.assertTrue(list(s.base.glob("mc-*/extfs-cache*.pag")), "ZIP alias semantics were bypassed")

    def test_zip_viewer_then_copy(self):
        s = self.session(skin="dotname-light")
        archive = s.left / "viewer.zip"
        contents = b"ZIP viewer test contents\n"
        self.zip_with_file(archive, contents)
        self.open_zip_panel(s, archive)
        s.keys("Home", "Down", "F3")
        s.wait(lambda t: "ZIP viewer test contents" in t, "ZIP viewer did not open")
        self.assertTrue(list(s.base.glob("mc-*/extfs-cache*.pag")), "Viewer did not use its temporary copy")
        s.keys("F10")
        s.wait(lambda t: "uzip://" in t and "file.txt" in t, "ZIP viewer did not close")
        self.copy_zip_file(s, contents)

    def test_zip_background_copy(self):
        s = self.session(skin="dotname-light")
        archive = s.left / "background.zip"
        contents = b"background contents\n"
        self.zip_with_file(archive, contents)
        self.open_zip_panel(s, archive)
        # Open the native archive in the parent before forking the copy job.
        self.copy_zip_file(s, contents)
        output = s.right / "file.txt"
        output.unlink()
        s.keys("Home", "Down", "F5")
        s.wait(lambda t: "source mask:" in t, "Copy dialog did not open")
        s.keys("M-b")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if output.is_file() and output.read_bytes() == contents:
                break
            time.sleep(.05)
        self.assertEqual(output.read_bytes(), contents)
        self.assertFalse(list(s.base.glob("mc-*/extfs-cache*.pag")), "Background copy used the helper")

    def test_skins_without_truecolor(self):
        for root in (False, True):
            with self.subTest(root=root):
                s = Session(Path(self.tmp.name) / str(root), truecolor=False, root=root)
                try:
                    screen = s.color("light", root)
                    self.assertNotIn("COLORTERM", screen)
                    self.assertNotIn("48;2;", screen)
                    for theme in ("dark", "light"):
                        s.keys("M-T")
                        screen = s.color(theme, root)
                        self.assertNotIn("COLORTERM", screen)
                        self.assertNotIn("48;2;", screen)
                        s.keys("Down", "DC")
                        s.wait(lambda t: "Trash file" in t,
                               "The trash dialog did not open without truecolor")
                        s.keys("Escape")
                        s.wait(lambda t: "Trash file" not in t,
                               "The trash dialog did not close")
                finally:
                    s.stop()

    def test_themes(self):
        cases = [
            (False, None, (), None, "light"),
            (False, "dotname-light", (), None, "light"),
            (False, "dotname-light-root", (), None, "light"),
            (True, None, (), None, "light"),
            (True, "default", (), None, "light"),
            (True, "dotname-dark", (), None, "dark"),
            (True, "dotname-dark-root", (), None, "dark"),
            (True, None, (), "dotname-dark", "dark"),
            (True, None, ("--skin=dotname-dark.ini",), None, "dark"),
        ]
        for index, (root, skin, args, envskin, start) in enumerate(cases):
            with self.subTest(root=root, skin=skin, args=args, envskin=envskin):
                s = Session(Path(self.tmp.name) / str(index), skin, root, args, envskin)
                try:
                    s.color(start, root)
                    s.keys("Down", "Insert")
                    s.wait(lambda t: "1 file" in t, "The file is not marked")
                    for theme in ["dark" if start == "light" else "light", start]:
                        s.keys("M-T")
                        screen = s.color(theme, root)
                        self.assertIn("1 file", screen)
                        self.assertIn("other.txt", screen)
                    s.keys("F10")
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        alive = subprocess.run(["tmux", "-S", s.socket, "has-session"],
                                               capture_output=True, timeout=5).returncode == 0
                        if not alive:
                            break
                        time.sleep(.05)
                    else:
                        self.fail("MC did not exit")
                    cfg = configparser.ConfigParser(interpolation=None, strict=False)
                    cfg.read(s.config / "ini")
                    self.assertEqual(cfg.get("Midnight-Commander", "skin"), "dotname-" + start)
                finally:
                    s.stop()

    def test_list_reload_and_invalid_skin(self):
        s = self.session()
        s.color("light")
        favorites = s.config / "skin-cycle"
        favorites.write_text("# seznam\n\ndotname-light\ndotname-dark\ndotname-dark\n")
        s.keys("M-T")
        s.color("dark")
        s.keys("M-T")
        s.color("light")
        favorites.write_text("dotname-light\nmissing-regression-skin\n")
        s.keys("M-T")
        s.wait(lambda t: "Unable to load" in t, "Missing error for a nonexistent skin")
        s.keys("Enter")
        s.color("light")
        favorites.write_text("dotname-dark\n")
        s.keys("M-T")
        s.color("dark")

    def test_trash_parent_directory(self):
        s = self.session()
        s.color("light")
        error = 'Cannot operate on ".."!'
        # Compare trash shortcuts with native deletion on the parent entry.
        for key in ("F8", "DC", "F12"):
            with self.subTest(key=key):
                s.keys("Home", key)
                screen = s.wait(lambda t: error in t, "Missing parent directory error")
                self.assertNotIn("Trash file", screen)
                self.assertTrue(s.file.exists())
                self.assertFalse((s.base / "data/Trash").exists())
                s.keys("Enter")
                s.wait(lambda t: error not in t, "The error dialog did not close")

        # Marked files take precedence over the cursor, including on "..".
        s.keys("Down", "Insert", "Home", "DC")
        s.wait(lambda t: "Trash file" in t,
               "The parent entry incorrectly blocked a marked file")
        s.keys("Escape")
        s.wait(lambda t: "Trash file" not in t,
               "The trash dialog did not close")
        self.assertTrue(s.file.exists())

    def test_trash_dialog_details(self):
        cases = [
            ([('café file.txt', False)], 'file', False),
            ([('folder', True)], 'directory', False),
            ([('first.txt', False), ('second.txt', False)], '2 files', True),
            ([('first', True), ('second', True)], '2 directories', True),
            ([('folder', True), ('file.txt', False)], '2 files/directories', True),
        ]
        for index, (items, detail, marked) in enumerate(cases):
            with self.subTest(detail=detail):
                s = Session(Path(self.tmp.name) / str(index))
                try:
                    s.color('light')
                    s.file.unlink()
                    for name, directory in items:
                        path = s.left / name
                        path.mkdir() if directory else path.write_text('keep me')
                    s.keys('C-r', 'Home', 'Down')
                    s.wait(lambda t: items[0][0] in t, 'Panel did not reload')
                    if marked:
                        for _ in items:
                            s.keys('Insert')
                        s.keys('Home')
                    for key, verb in [('F8', 'Delete'), ('DC', 'Trash')]:
                        s.keys(key)
                        screen = s.wait(lambda t: verb + ' ' + detail in t,
                                        'Missing selection details for ' + verb)
                        if not marked:
                            self.assertIn('"' + items[0][0] + '"?', screen)
                        s.keys('Escape')
                        s.wait(lambda t: verb + ' ' + detail not in t,
                               'The confirmation dialog did not close')
                    for name, _ in items:
                        self.assertTrue((s.left / name).exists())
                finally:
                    s.stop()

    def test_trash_safe_delete(self):
        s = self.session(skin='dotname-light', safe_delete=True)
        s.color('light')
        s.keys('Down', 'DC')
        s.wait(lambda t: 'Trash file' in t, 'Missing trash confirmation')
        s.keys('Enter')
        s.wait(lambda t: 'Trash file' not in t, 'The dialog did not close')
        self.assertTrue(s.file.exists())

    def test_trash_cancel_and_confirm(self):
        s = self.session()
        s.color("light")
        s.keys("Down", "DC")
        s.wait(lambda t: "Trash file" in t, "Missing trash confirmation")
        s.keys("Escape")
        s.wait(lambda t: "Trash file" not in t, "The dialog did not close")
        self.assertTrue(s.file.exists())
        s.keys("F12")
        s.wait(lambda t: "Trash file" in t, "Missing trash confirmation")
        s.keys("Enter")
        deadline = time.monotonic() + 8
        trash = s.base / "data/Trash/files" / s.file.name
        while time.monotonic() < deadline and not trash.exists():
            time.sleep(.05)
        self.assertTrue(trash.exists(), s.tmux("capture-pane", "-t", "test", "-p", "-S", "-200"))
        self.assertEqual(trash.read_text(), "test content\n")
        self.assertFalse(s.file.exists())
        self.assertTrue((s.base / "data/Trash/info" / (s.file.name + ".trashinfo")).exists())

    def test_delete_command_line(self):
        s = self.session()
        s.color("light")
        s.keys("Down", "echo café", "C-a", "DC")
        s.wait(lambda t: "cho café" in t and "echo café" not in t,
               "Delete did not remove the first command character")
        s.keys("C-e", "Left", "DC")
        s.wait(lambda t: "cho caf" in t and "cho café" not in t,
               "Delete did not remove the Unicode character")
        # Delete at the end of a nonempty line must not open the trash dialog.
        s.keys("C-e", "DC", "__end__")
        screen = s.wait(lambda t: "cho caf__end__" in t,
                        "Delete at the end of the command interrupted typing")
        self.assertNotIn("Trash file", screen)
        for key, message in (("F12", "Trash file"),
                             ("F8", "Delete file"), ("S-DC", "Delete file")):
            s.keys(key)
            s.wait(lambda t: message in t, "Missing confirmation for " + key)
            s.keys("Escape")
            s.wait(lambda t: message not in t, "The dialog did not close")
            self.assertTrue(s.file.exists())
        # Even a single space belongs to the command; removing it restores the trash action.
        s.keys("C-a", "C-k", "Space", "C-a", "DC", "DC")
        s.wait(lambda t: "Trash file" in t,
               "Delete did not open trash after the command line was cleared")
        s.keys("Escape")
        self.assertTrue(s.file.exists())

    def test_clipboard_shortcuts_without_config(self):
        for key in ("M-F", "M-D", "M-N", "M-C"):
            with self.subTest(key=key):
                s = Session(Path(self.tmp.name) / key)
                try:
                    s.color("light")
                    s.keys("Down", key)
                    s.wait(lambda t: "Copy failed: wl-copy" in t or "Copy failed: wl-copy" in
                           s.tmux("capture-pane", "-t", "test", "-a", "-q", "-p"),
                           "Shortcut did not invoke the clipboard helper: " + key)
                    self.assertTrue(s.file.exists())
                finally:
                    s.stop()

    def test_default_menu_and_original_shortcut(self):
        s = self.session()
        s.color("light")
        s.keys("M-c")
        s.wait(lambda t: "Quick cd" in t, "Alt+C did not open the change directory dialog")
        s.keys("Escape")
        s.wait(lambda t: "Quick cd" not in t, "The dialog did not close")
        s.keys("F2")
        s.wait(lambda t: "Copy full path" in t and "Copy item name" in t,
               "The default menu is missing clipboard actions")
        s.keys("Escape")



class ClipboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("mc_clipboard", HELPER)
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)

    def invoke(self, mode, path, process):
        process.__enter__.return_value = process
        with patch("sys.argv", ["mc-clipboard", mode, str(path)]), \
                patch.object(self.helper.subprocess, "Popen", return_value=process) as popen:
            self.helper.main()
        return popen

    def test_payloads_and_symlink(self):
        with tempfile.TemporaryDirectory(prefix="mc-clipboard-test-") as directory:
            link = Path(directory) / "link é #.txt"
            link.symlink_to("target.txt")
            for mode, expected in {"path": str(link), "directory": directory,
                                   "name": link.name, "file": link.as_uri() + "\r\n"}.items():
                with self.subTest(mode=mode):
                    process = MagicMock(returncode=0)
                    popen = self.invoke(mode, link, process)
                    process.communicate.assert_called_once_with(os.fsencode(expected), timeout=5)
                    mime = "text/uri-list" if mode == "file" else "text/plain;charset=utf-8"
                    self.assertEqual(popen.call_args.args[0][1:], ["--type", mime])

    def test_clipboard_errors(self):
        for error in [subprocess.TimeoutExpired("wl-copy", 5), KeyboardInterrupt()]:
            with self.subTest(error=type(error).__name__):
                process = MagicMock(returncode=0)
                process.communicate.side_effect = error
                with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as caught:
                    self.invoke("path", Path("/tmp/file"), process)
                self.assertEqual(caught.exception.code, 130 if isinstance(error, KeyboardInterrupt) else 1)
                process.kill.assert_called_once()
                process.wait.assert_called_once()
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as caught:
            self.invoke("path", Path("/tmp/file"), MagicMock(returncode=1))
        self.assertEqual(caught.exception.code, 1)


if __name__ == "__main__":
    if os.geteuid() == 0:
        raise SystemExit("Run the tests as a regular user, without sudo.")
    probe = subprocess.run(["unshare", "--user", "--map-root-user", "id", "-u"],
                           capture_output=True, text=True, timeout=5)
    if probe.returncode or probe.stdout.strip() != "0":
        raise SystemExit("The tests require enabled user namespaces (unshare -Ur).")
    unittest.main(verbosity=2)
