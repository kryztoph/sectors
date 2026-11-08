from __future__ import annotations

import importlib.util
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sectors import cli

spec = importlib.util.spec_from_file_location("publisher", Path(__file__).resolve().parents[1] / "scripts/publish_to_csfox_gh.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PublishingTests(unittest.TestCase):
    def test_defaults_and_supported_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(publisher._repo_name(), "kryztoph/csfox-reports")
        for key in ("SECTORS_PUBLISH_REPO", "SECTORS_PUBLISH_REPO_URL", "SECTORS_REPORTS_REPO_URL"):
            for value in ("other/reports", "https://github.com/other/reports.git", "git@github.com:other/reports.git"):
                with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}, clear=True):
                    self.assertEqual(publisher._repo_name(), "other/reports")
        publisher._validate_target("other/reports", "review/candidates")
        with self.assertRaises(ValueError):
            publisher._validate_target("kryztoph/csfox-reports", "main")

    def test_frontend_overrides_fail_before_any_github_call(self):
        for key in ("SECTORS_PUBLISH_REPO", "SECTORS_PUBLISH_REPO_URL", "SECTORS_REPORTS_REPO_URL"):
            for value in ("kryztoph/csfox", "KRYZTOPH/CSFOX", "https://github.com/kryztoph/csfox.git", "git@github.com:kryztoph/csfox.git"):
                with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}, clear=True), patch.object(publisher, "_gh_json") as api:
                    with self.assertRaisesRegex(ValueError, "frontend"):
                        publisher.main()
                    api.assert_not_called()
        with patch.dict(os.environ, {"SECTORS_PUBLISH_REPO": "other/reports", "SECTORS_REPORTS_REPO_URL": "kryztoph/csfox"}, clear=True):
            with self.assertRaisesRegex(ValueError, "frontend"):
                publisher._repo_name()

    def test_malformed_configuration_rejected(self):
        for value in ("https://example.com/kryztoph/csfox-reports", "foo/bar/baz", "foo/..", "foo/bar?x=1", "https://github.com/foo/bar#ref"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                publisher._parse_repo(value)
        for branch in ("", "../master", "master?ref=main", "master//main"):
            with self.subTest(branch=branch), self.assertRaises(ValueError):
                publisher._validate_target("other/reports", branch)

    def test_canonical_frontend_redirect_rejected_before_writes(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), patch.object(publisher, "PROJECT_DIR", Path(tmp)), patch.object(publisher, "_publish_files", return_value=[]), patch.object(publisher, "_gh_json", return_value={"full_name": "kryztoph/csfox"}) as api, patch.object(publisher.os, "chdir"):
            with self.assertRaisesRegex(ValueError, "frontend"):
                publisher.main()
            self.assertEqual(api.call_count, 1)
            self.assertEqual(api.call_args.args, ("repos/kryztoph/csfox-reports",))

    def test_publication_transaction_only_writes_reports_repo_master(self):
        calls = []
        def fake_api(endpoint, method="GET", body=None):
            calls.append((endpoint, method, body))
            self.assertTrue(endpoint.startswith("repos/kryztoph/csfox-reports/"), endpoint)
            if endpoint.endswith("/git/ref/heads/master"):
                return {"object": {"sha": "old-commit"}}
            if endpoint.endswith("/git/commits/old-commit"):
                return {"tree": {"sha": "old-tree"}}
            if "?recursive" in endpoint:
                return {"tree": []}
            if endpoint.endswith("/git/blobs"):
                return {"sha": "blob"}
            if endpoint.endswith("/git/trees"):
                self.assertEqual(body["base_tree"], "old-tree")
                self.assertTrue(all(item["path"].startswith("reports/sectors/candidates/") for item in body["tree"]))
                return {"sha": "new-tree"}
            if endpoint.endswith("/git/commits"):
                self.assertEqual(body["parents"], ["old-commit"])
                return {"sha": "new-commit"}
            if endpoint.endswith("/git/refs/heads/master"):
                self.assertEqual(body, {"sha": "new-commit", "force": False})
                return {}
            self.fail(endpoint)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "reports/candidates"
            directory.mkdir(parents=True)
            for name in ("latest.md", "latest.html", "latest.json"):
                (directory / name).write_text("test output")
            old_cwd = Path.cwd()
            try:
                with patch.dict(os.environ, {}, clear=True), patch.object(publisher, "PROJECT_DIR", root), patch.object(publisher, "BRANCH", "master"), patch.object(publisher, "LOGO_SOURCE", root / "missing"), patch.object(publisher, "_gh_json") as api, patch("builtins.print"):
                    def dispatch(endpoint, method="GET", body=None):
                        if endpoint == "repos/kryztoph/csfox-reports":
                            return {"full_name": "kryztoph/csfox-reports"}
                        return fake_api(endpoint, method, body)
                    api.side_effect = dispatch
                    self.assertEqual(publisher.main(), 0)
            finally:
                os.chdir(old_cwd)
        self.assertEqual(sum(method == "PATCH" for _, method, _ in calls), 1)

    def test_missing_master_fails_before_blob_creation(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(publisher.os, "chdir"), patch.object(publisher, "_publish_files", return_value=[]), patch.object(publisher, "_gh_json") as api:
            api.side_effect = [{"full_name": "kryztoph/csfox-reports"}, RuntimeError("master missing")]
            with self.assertRaisesRegex(RuntimeError, "master missing"):
                publisher.main()
            self.assertTrue(all(not call.kwargs for call in api.call_args_list))

    def test_unchanged_tree_never_creates_commit(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(publisher.os, "chdir"), patch.object(publisher, "_publish_files", return_value=[]), patch.object(publisher, "_gh_json") as api, patch("builtins.print"):
            api.side_effect = [{"full_name": "kryztoph/csfox-reports"}, {"object": {"sha": "base"}},
                               {"tree": {"sha": "same"}}, {"tree": []}, {"sha": "same"}]
            self.assertEqual(publisher.main(), 0)
            self.assertEqual(api.call_count, 5)
            self.assertFalse(any(call.args[0].endswith("/git/commits") for call in api.call_args_list))

    def test_cli_publisher_uses_current_worktree(self):
        with TemporaryDirectory() as tmp, patch.object(cli, "ROOT", Path(tmp)), patch.dict(os.environ, {}, clear=True), patch.object(cli.subprocess, "run") as run:
            script = Path(tmp) / "scripts/publish_to_reports_repo.sh"
            script.parent.mkdir()
            script.touch()
            run.return_value.returncode = 0
            self.assertEqual(cli._publish_to_reports_repo(), 0)
            self.assertEqual(run.call_args.kwargs["env"]["SECTORS_PROJECT_DIR"], tmp)
            self.assertEqual(run.call_args.kwargs["cwd"], Path(tmp))


if __name__ == "__main__":
    unittest.main()
