"""Portable installer tests using tiny local fixtures; no dependency/model downloads."""

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
SCRIPTS = APP.parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import install as installer
import check as checker
import _common as common

spec = importlib.util.spec_from_file_location("packaged_download_models", APP / "download_models.py")
downloader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloader)


def status(**overrides):
    result = {"exists": True, "python_compatible": True, "dependencies_ready": True,
              "platform_supported": True, "model_ready": True, "ocr_available": True,
              "free_bytes": 8 * 1024 ** 3, "ready": True}
    result.update(overrides)
    return result


class InstallerTests(unittest.TestCase):
    def test_supported_platform_requires_macos14_apple_silicon(self):
        for system, machine, version, expected in (("Darwin", "arm64", "14.0", True), ("Darwin", "arm64", "15.1", True), ("Darwin", "arm64", "13.9", False), ("Darwin", "x86_64", "14.0", False), ("Linux", "arm64", "", False)):
            with self.subTest(version=version, machine=machine), patch.object(installer.platform, "system", return_value=system), patch.object(installer.platform, "machine", return_value=machine), patch.object(installer.platform, "mac_ver", return_value=(version, (), "")):
                self.assertEqual(installer.platform_supported(), expected)

    def test_healthy_installation_is_preserved_when_disk_low_and_uv_missing(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(installer, "inspect_installation", return_value=status(free_bytes=0)), patch.object(installer, "run_step") as run, patch.object(installer.shutil, "which", return_value=None):
            app = Path(folder)
            result = installer.install(app)
            self.assertTrue(result["ready"])
            self.assertEqual(list(app.iterdir()), [])
            run.assert_not_called()

    def test_low_disk_preflight_does_not_create_cache_venv_or_lock(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(installer, "inspect_installation", return_value=status(ready=False, model_ready=False, free_bytes=1024)), patch.object(installer, "run_step") as run:
            app = Path(folder)
            with self.assertRaises(installer.SetupError) as caught:
                installer.install(app)
            self.assertIn("6 GiB", str(caught.exception))
            self.assertEqual(list(app.iterdir()), [])
            run.assert_not_called()

    def test_check_only_never_calls_mutating_install_steps(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(installer, "inspect_installation", return_value=status(ready=False, model_ready=False, free_bytes=0)), patch.object(installer, "install") as install, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(installer.main(["--app-dir", folder, "--check-only", "--with-ocr"]), 1)
            install.assert_not_called()
            self.assertTrue(json.loads(output.getvalue())["read_only"])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_actual_check_only_without_bytecode_flag_leaves_app_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            for name in ("requirements.lock.txt", "download_models.py", "launch.py"):
                shutil.copyfile(APP / name, app / name)
            before = {str(path.relative_to(app)): (path.stat().st_size, path.stat().st_mtime_ns) for path in app.rglob("*")}
            response = subprocess.run([sys.executable, str(SCRIPTS / "install.py"), "--app-dir", str(app), "--check-only"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            self.assertEqual(response.returncode, 1)  # Fresh app is intentionally uninstalled.
            self.assertTrue(json.loads(response.stdout)["read_only"])
            after = {str(path.relative_to(app)): (path.stat().st_size, path.stat().st_mtime_ns) for path in app.rglob("*")}
            self.assertEqual(before, after)

    def test_dependency_repair_reuses_existing_environment_and_model(self):
        initial = status(ready=False, dependencies_ready=False)
        with tempfile.TemporaryDirectory() as folder, patch.object(installer, "inspect_installation", side_effect=[initial, status()]), patch.object(installer.shutil, "which", return_value="/local/uv"), patch.object(installer, "run_step") as run, contextlib.redirect_stdout(io.StringIO()):
            app = Path(folder)
            marker = app / "existing-model-marker"
            marker.write_text("preserve")
            self.assertTrue(installer.install(app)["ready"])
            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ["/local/uv", "pip", "install"])
            self.assertIn(str(app / ".venv" / "bin" / "python"), command)
            self.assertEqual(marker.read_text(), "preserve")

    def test_fresh_setup_uses_managed_python_and_pinned_files(self):
        initial = status(exists=False, python_compatible=False, dependencies_ready=False, model_ready=False, ready=False)
        with tempfile.TemporaryDirectory() as folder, patch.object(installer, "inspect_installation", side_effect=[initial, status()]), patch.object(installer.shutil, "which", return_value="/local/uv"), patch.object(installer, "run_step") as run, contextlib.redirect_stdout(io.StringIO()):
            app = Path(folder)
            installer.install(app)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(len(commands), 3)
            self.assertEqual(commands[0][:2], ["/local/uv", "venv"])
            self.assertIn("--managed-python", commands[0])
            self.assertIn("3.12", commands[0])
            self.assertNotIn("--clear", commands[0])
            self.assertEqual(commands[2][-1], str(app / "download_models.py"))

    def test_incompatible_or_unfinished_environment_is_preserved(self):
        for exists in (True, False):
            with self.subTest(exists=exists), tempfile.TemporaryDirectory() as folder, patch.object(installer, "inspect_installation", return_value=status(exists=exists, python_compatible=False, dependencies_ready=False, ready=False)), patch.object(installer, "run_step") as run:
                app = Path(folder)
                (app / ".venv").mkdir()
                marker = app / ".venv" / "marker"
                marker.write_text("preserve")
                with self.assertRaises(installer.SetupError):
                    installer.install(app)
                self.assertEqual(marker.read_text(), "preserve")
                run.assert_not_called()

    def test_symlink_installation_folder_is_never_modified(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as other, patch.object(installer, "inspect_installation", return_value=status(ready=False, dependencies_ready=False)), patch.object(installer, "run_step") as run:
            app = Path(folder)
            (app / ".setup-cache").symlink_to(other, target_is_directory=True)
            with self.assertRaises(installer.SetupError):
                installer.install(app)
            self.assertEqual(list(Path(other).iterdir()), [])
            run.assert_not_called()

    def test_missing_uv_has_actionable_official_instructions(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(installer, "inspect_installation", return_value=status(ready=False, dependencies_ready=False)), patch.object(installer.shutil, "which", return_value=None):
            with self.assertRaises(installer.SetupError) as caught:
                installer.install(Path(folder))
            self.assertIn("brew install uv", str(caught.exception))
            self.assertIn("docs.astral.sh", str(caught.exception))

    def test_ocr_is_optional_and_homebrew_only_with_explicit_flag(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(installer, "inspect_installation", return_value=status(ocr_available=False)), patch.object(installer, "run_step") as run:
            self.assertTrue(installer.install(Path(folder))["ready"])
            run.assert_not_called()
        with tempfile.TemporaryDirectory() as folder, patch.object(installer, "inspect_installation", side_effect=[status(ocr_available=False), status()]), patch.object(installer.shutil, "which", side_effect=lambda name: "/local/brew" if name == "brew" else None), patch.object(installer, "run_step") as run, contextlib.redirect_stdout(io.StringIO()):
            installer.install(Path(folder), with_ocr=True)
            self.assertEqual(run.call_args.args[0], ["/local/brew", "install", "poppler", "tesseract"])

    def test_setup_environment_keeps_python_and_cache_app_local(self):
        environment = installer.setup_environment(Path("/example/app"))
        self.assertEqual(environment["UV_PYTHON_INSTALL_DIR"], "/example/app/.python")
        self.assertEqual(environment["UV_CACHE_DIR"], "/example/app/.setup-cache")
        self.assertEqual(environment["HF_HUB_DISABLE_IMPLICIT_TOKEN"], "1")
        self.assertNotIn("PYTHONPATH", environment)

    def test_success_cache_cleanup_targets_only_app_cache(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(installer.subprocess, "run") as run:
            app = Path(folder)
            (app / ".setup-cache").mkdir()
            installer.clean_success_cache(app, "/local/uv")
            self.assertEqual(run.call_args.args[0], ["/local/uv", "cache", "clean", "--no-config", "--cache-dir", str(app / ".setup-cache")])
            self.assertNotIn(str(app / ".python"), run.call_args.args[0])

    def test_failed_setup_keeps_cache_for_resume(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(installer, "inspect_installation", return_value=status(ready=False, dependencies_ready=False)), patch.object(installer.shutil, "which", return_value="/local/uv"), patch.object(installer, "run_step", side_effect=installer.SetupError("synthetic failure")), patch.object(installer, "clean_success_cache") as clean, contextlib.redirect_stdout(io.StringIO()):
            app = Path(folder)
            (app / ".setup-cache").mkdir()
            marker = app / ".setup-cache" / "partial-public-download"
            marker.write_text("resume")
            with self.assertRaises(installer.SetupError):
                installer.install(app)
            self.assertEqual(marker.read_text(), "resume")
            clean.assert_not_called()

    def test_all_model_checksums_pinned_and_missing_assets_fail_read_only(self):
        self.assertEqual(len(downloader.MODEL_ASSETS), 6)
        self.assertEqual(downloader.MODEL_REVISION, "1cb4166094dc58fa8d836429f060d6c95f62b495")
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(downloader.verify_model_assets(Path(folder)))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_public_model_download_resumes_and_verifies_each_exact_asset(self):
        files = {"config.json": b'{"synthetic": true}', "model.safetensors": b"synthetic weight bytes"}
        assets = {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in files.items()}
        calls = []
        def download(**kwargs):
            calls.append(kwargs)
            target = Path(kwargs["local_dir"]) / kwargs["filename"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(files[kwargs["filename"]])
        with tempfile.TemporaryDirectory() as folder, patch.object(downloader, "ROOT", Path(folder)), patch.object(downloader, "MODEL_ASSETS", assets), patch.dict(sys.modules, {"huggingface_hub": types.SimpleNamespace(hf_hub_download=download)}), patch.dict(downloader.os.environ, {}, clear=False):
            local = Path(folder) / "models" / "gliner2-pii"
            local.mkdir(parents=True)
            (local / "config.json").write_bytes(files["config.json"])
            downloader.download()
            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0]["token"])
            self.assertEqual(calls[0]["revision"], downloader.MODEL_REVISION)
            self.assertEqual(calls[0]["filename"], "model.safetensors")
            self.assertFalse(calls[0]["force_download"])
            self.assertTrue(downloader.verify_model_assets(local))
            provenance = json.loads((Path(folder) / "models" / "provenance.json").read_text())
            self.assertTrue(all(item["pinned_sha256_verified"] for item in provenance["downloaded_files"]))
            downloader.download()
            self.assertEqual(len(calls), 1)

    def test_model_with_unexpected_executable_artifact_is_not_ready(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(downloader, "MODEL_ASSETS", {}):
            local = Path(folder)
            artifact = local / "remote.py"
            artifact.write_text("synthetic")
            self.assertFalse(downloader.verify_model_assets(local))
            self.assertEqual(artifact.read_text(), "synthetic")

    def test_health_requires_service_identity_workspace_offline_and_documents(self):
        app = Path("/synthetic/app")
        payload = {"service": common.SERVICE_ID, "workspace_id": common.workspace_id(app),
                   "feature_revision": common.FEATURE_REVISION, "ready": True, "offline": True,
                   "supported_file_extensions": ["csv", "xlsx", "docx", "pdf"]}
        self.assertTrue(common.matches_health(payload, app))
        for key, value in (("workspace_id", "wrong"), ("offline", False), ("feature_revision", "old"), ("ready", False)):
            changed = dict(payload)
            changed[key] = value
            self.assertFalse(common.matches_health(changed, app))


if __name__ == "__main__":
    unittest.main()
