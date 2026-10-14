"""Offline safety and deployment tests (Python standard library only)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.parse import parse_qs

REPO = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("qb_standalone_cli", str(REPO / "stack"))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
stack = importlib.util.module_from_spec(spec)
loader.exec_module(stack)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.env = stack.parse_env(REPO / ".env.example")

    def test_default_config_is_valid_and_collision_safe(self):
        stack.validate(self.env)
        self.assertEqual(self.env["WEBUI_PORT"], "8081")
        self.assertEqual(self.env["TORRENTING_PORT"], "6882")
        self.assertEqual(self.env["WG_BIND_IP"], "")
        self.assertNotEqual(self.env["CONFIG_ROOT"], self.env["DATA_ROOT"])

    def test_invalid_port_and_root_user_rejected(self):
        for key, value in (("WEBUI_PORT", "80"), ("WEBUI_PORT", "70000"),
                           ("TORRENTING_PORT", "8081"), ("PUID", "0"), ("PGID", "root")):
            with self.subTest(key=key, value=value):
                modified = {**self.env, key: value}
                with self.assertRaises(stack.SetupError):
                    stack.validate(modified)

    def test_public_wireguard_address_and_missing_ip_rejected(self):
        for ip in ("", "0.0.0.0", "127.0.0.1", "8.8.8.8", "bad", "ff::1"):
            with self.subTest(ip=ip):
                with self.assertRaises(stack.SetupError):
                    stack.validate({**self.env, "WG_BIND_IP": ip}, vpn=True)
        stack.validate({**self.env, "WG_BIND_IP": "10.77.0.2"}, vpn=True)

    def test_paths_cannot_be_system_dirs_or_nested(self):
        for bad in ("/", "/etc/passwd", "/dev", "data/relative", "/srv/../etc"):
            with self.subTest(bad=bad):
                with self.assertRaises(stack.SetupError):
                    stack.validate({**self.env, "DATA_ROOT": bad})
        with self.assertRaises(stack.SetupError):
            stack.validate({**self.env, "CONFIG_ROOT": "/srv/qbittorrent",
                            "DATA_ROOT": "/srv/qbittorrent/data"})

    def test_symlink_component_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "target").mkdir()
            (base / "link").symlink_to(base / "target", target_is_directory=True)
            with self.assertRaises(stack.SetupError):
                stack.validate({**self.env, "DATA_ROOT": str(base / "link" / "new")})

    def test_env_is_literal_only_and_duplicate_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = Path(directory) / ".env"
            filepath.write_text((REPO / ".env.example").read_text() + "\nPUID=2000\n")
            with self.assertRaisesRegex(stack.SetupError, "duplicate"):
                stack.parse_env(filepath)
            filepath.write_text((REPO / ".env.example").read_text().replace("PUID=1000", "PUID=$(id)"))
            with self.assertRaisesRegex(stack.SetupError, "literal"):
                stack.parse_env(filepath)
            filepath.write_text((REPO / ".env.example").read_text() + "\nUNEXPECTED=value\n")
            with self.assertRaisesRegex(stack.SetupError, "unknown"):
                stack.parse_env(filepath)

    def test_wireguard_runtime_must_have_matching_interface_and_ip(self):
        env = {**self.env, "WG_BIND_IP": "10.77.0.2"}
        def fake_run(command, **kwargs):
            if command[:2] == ["wg", "show"]:
                return SimpleNamespace(stdout="wg0\n")
            return SimpleNamespace(stdout=json.dumps([{"addr_info": [
                {"family": "inet", "local": "10.77.0.2"}]}]))
        with mock.patch.object(stack, "run", side_effect=fake_run):
            stack.verify_vpn_interface(env)
        with mock.patch.object(stack, "run", return_value=SimpleNamespace(stdout="eth0\n")):
            with self.assertRaisesRegex(stack.SetupError, "not a running WireGuard"):
                stack.verify_vpn_interface(env)

    def test_compose_overlay_flag_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "images.lock.env"
            lock.write_text("QBITTORRENT_IMAGE=lscr.io/linuxserver/qbittorrent@sha256:" + "a" * 64)
            with mock.patch.object(stack, "IMAGE_LOCK", lock):
                command = stack.compose_command(self.env, media=True, vpn=True)
            self.assertIn(str(REPO / "compose.yaml"), command)
            self.assertIn(str(REPO / "compose.media.yaml"), command)
            self.assertIn(str(REPO / "compose.wireguard.yaml"), command)
            self.assertIn(self.env["PROJECT_NAME"], command)


class StorageAndBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = stack.parse_env(REPO / ".env.example")
        if os.getuid() == 0:
            self.env["PUID"] = "1000"
            self.env["PGID"] = "1000"
        else:
            self.env["PUID"] = str(os.getuid())
            self.env["PGID"] = str(os.getgid())
        self.env["CONFIG_ROOT"] = str(self.base / "config")
        self.env["DATA_ROOT"] = str(self.base / "data")

    def test_prepare_creates_isolated_categories_idempotently(self):
        stack.prepare(self.env)
        sentinel = self.base / "data" / "torrents" / "standalone" / "books" / "keep.txt"
        sentinel.write_text("do not overwrite")
        stack.prepare(self.env)
        self.assertEqual(sentinel.read_text(), "do not overwrite")
        self.assertTrue((self.base / "data/torrents/standalone/incomplete").is_dir())
        self.assertEqual((self.base / "data/torrents/standalone/books").stat().st_uid, int(self.env["PUID"]))

    def test_prepare_refuses_existing_category_wrong_owner(self):
        stack.prepare(self.env)
        folder = self.base / "data/torrents/standalone/books"
        with mock.patch.object(stack, "ensure_ownership", side_effect=stack.SetupError("owner mismatch")):
            with self.assertRaisesRegex(stack.SetupError, "owner mismatch"):
                stack.prepare(self.env)
        self.assertTrue(folder.exists())

    def test_backup_does_not_include_downloads_and_rejects_overwrite(self):
        stack.prepare(self.env)
        (Path(self.env["CONFIG_ROOT"]) / "qBittorrent.conf").write_text("mock-settings")
        (Path(self.env["DATA_ROOT"]) / "torrents/standalone/books/important.iso").write_text("mock-content")
        fake_env = self.base / ".env"
        fake_env.write_text("mock-env")
        fake_lock = self.base / "images.lock.env"
        fake_lock.write_text("mock-lock")
        archive = self.base / "safe.tar.gz"
        with (mock.patch.object(stack, "ENV_FILE", fake_env), mock.patch.object(stack, "IMAGE_LOCK", fake_lock),
              mock.patch.object(stack, "running_container", return_value=False)):
            stack.backup(self.env, archive)
            with self.assertRaisesRegex(stack.SetupError, "already exists"):
                stack.backup(self.env, archive)
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
        self.assertIn("config/qBittorrent.conf", names)
        self.assertIn("images.lock.env", names)
        self.assertIn(".env", names)
        self.assertFalse(any("important.iso" in name for name in names))
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_backup_rejects_symlinks(self):
        stack.prepare(self.env)
        (Path(self.env["CONFIG_ROOT"]) / "outside").symlink_to(self.base)
        fake_env = self.base / ".env"
        fake_env.write_text("ok")
        fake_lock = self.base / "images.lock.env"
        fake_lock.write_text("ok")
        archive = self.base / "reject.tar.gz"
        with (mock.patch.object(stack, "ENV_FILE", fake_env), mock.patch.object(stack, "IMAGE_LOCK", fake_lock),
              mock.patch.object(stack, "running_container", return_value=False)):
            with self.assertRaisesRegex(stack.SetupError, "symlinks"):
                stack.backup(self.env, archive)
        self.assertFalse(archive.exists())


class ImageLockTests(unittest.TestCase):
    def test_resolve_image_digest_and_refuse_automatic_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "images.lock.env"
            prev = Path(directory) / "images.lock.env.previous"
            env = stack.parse_env(REPO / ".env.example")
            digest = "lscr.io/linuxserver/qbittorrent@sha256:" + "a" * 64
            def fake_run(args, **kwargs):
                if args[:2] == ["docker", "pull"]:
                    return SimpleNamespace(stdout="ok")
                if args[:3] == ["docker", "image", "inspect"]:
                    return SimpleNamespace(stdout=json.dumps([digest]))
                raise AssertionError(args)
            with (mock.patch.object(stack, "IMAGE_LOCK", lock),
                  mock.patch.object(stack, "IMAGE_PREVIOUS", prev),
                  mock.patch.object(stack, "ROOT", Path(directory)),
                  mock.patch.object(stack, "run", side_effect=fake_run)):
                stack.lock_image(env)
                self.assertIn(digest, lock.read_text())
                self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
                stack.lock_image(env)  # must not fetch again
                stack.lock_image(env, refresh=True)
                self.assertTrue(prev.exists())


class CategoryAPITests(unittest.TestCase):
    def test_configures_paths_using_only_loopback_and_password_prompt(self):
        env = stack.parse_env(REPO / ".env.example")
        recorded = []
        categories: dict[str, dict[str, str]] = {}
        prefs: dict[str, object] = {}

        class Response:
            def __init__(self, payload):
                self.payload = payload
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return self.payload.encode("utf-8")

        class Opener:
            def open(self, request, timeout=10):
                self.assert_request(request)
                path = request.full_url.split("/api/v2/")[-1]
                data = parse_qs(request.data.decode()) if request.data else {}
                recorded.append((path, data))
                if path == "auth/login":
                    self.assert_login(data)
                    return Response("Ok.")
                if path == "torrents/categories":
                    return Response(json.dumps(categories))
                if path == "torrents/createCategory":
                    categories[data["category"][0]] = {"savePath": data["savePath"][0]}
                    return Response("")
                if path == "app/setPreferences":
                    prefs.update(json.loads(data["json"][0]))
                    return Response("")
                if path == "app/preferences":
                    return Response(json.dumps(prefs))
                raise AssertionError(path)
            @staticmethod
            def assert_request(request):
                assert request.full_url.startswith("http://127.0.0.1:8081/api/v2/")
            @staticmethod
            def assert_login(data):
                assert data["password"] == ["example-temp-password"]

        with mock.patch.object(stack.getpass, "getpass", return_value="example-temp-password"):
            with mock.patch.object(stack.urllib.request, "build_opener", return_value=Opener()):
                stack.configure_categories(env)
                self.assertEqual(len(categories), 6)
                self.assertTrue(prefs["auto_tmm_enabled"])
                stack.configure_categories(env)  # existing paths preserved
                self.assertEqual(len(categories), 6)
        self.assertEqual(categories["tv"]["savePath"], "/data/torrents/standalone/tv")
        self.assertEqual(len([path for path, _ in recorded if path == "torrents/createCategory"]), 6)


class ComposeStructureTests(unittest.TestCase):
    def test_files_are_yaml_and_security_stays_opt_in(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("Optional PyYAML not available in this environment")
        base = yaml.safe_load((REPO / "compose.yaml").read_text())
        media = yaml.safe_load((REPO / "compose.media.yaml").read_text())
        vpn = yaml.safe_load((REPO / "compose.wireguard.yaml").read_text())
        service = base["services"]["qbittorrent"]
        self.assertEqual(len(service["ports"]), 1, "No P2P mappings in default mode")
        self.assertEqual(service["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(service["ports"][0]["protocol"], "tcp")
        self.assertEqual(media["services"]["qbittorrent"]["networks"]["shared"]["aliases"],
                         ["qbittorrent-standalone"])
        self.assertTrue(media["networks"]["shared"]["external"])
        self.assertIn("WG_BIND_IP", vpn["services"]["qbittorrent"]["ports"][0]["host_ip"])
        self.assertNotIn("volumes", vpn["services"]["qbittorrent"])
        self.assertNotIn("ports", media["services"]["qbittorrent"])
        for volume in service["volumes"]:
            self.assertFalse(volume["bind"]["create_host_path"])

    def test_bilingual_link_targets_exist(self):
        english = (REPO / "README.md").read_text()
        spanish = (REPO / "docs/README.es.md").read_text()
        self.assertIn("[Leer en español](docs/README.es.md)", english)
        self.assertIn("[Read in English](../README.md)", spanish)
        for file in (english, spanish):
            self.assertIn("./stack categories", file)
            self.assertIn("./stack up --media", file)
            self.assertIn("./stack up --vpn", file)
            self.assertIn("--refresh", file)


if __name__ == "__main__":
    unittest.main()
