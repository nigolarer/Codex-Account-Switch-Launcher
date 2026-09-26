import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SERVER_PATH = Path(__file__).resolve().parents[1] / "app" / "server.py"
SPEC = importlib.util.spec_from_file_location("codex_switcher_binary_server", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class CodexBinaryTests(unittest.TestCase):
    def test_finds_cli_in_current_chatgpt_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "ChatGPT.app"
            binary = app / "Contents/Resources/codex-cli/bin/codex"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)

            with mock.patch.object(server, "CHATGPT_APP", str(app)), mock.patch.object(
                server.shutil, "which", return_value=None
            ):
                self.assertEqual(server._codex_binary(), binary)

    def test_legacy_bundle_path_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "ChatGPT.app"
            binary = app / "Contents/Resources/codex"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)

            with mock.patch.object(server, "CHATGPT_APP", str(app)), mock.patch.object(
                server.shutil, "which", return_value=None
            ):
                self.assertEqual(server._codex_binary(), binary)


if __name__ == "__main__":
    unittest.main()
