import subprocess
import unittest
from unittest.mock import MagicMock, patch, call
import json


from release_automation.scripts.github_client import GitHubClient, GitHubClientError, Branch, Release

class TestGitHubClient(unittest.TestCase):
    def setUp(self):
        self.repo = "owner/repo"
        self.token = "fake-token"
        self.client = GitHubClient(self.repo, self.token)

    @patch("subprocess.run")
    def test_run_gh_success(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "output\n"
        mock_run.return_value = mock_result
        
        output = self.client._run_gh(["some", "cmd"])
        
        self.assertEqual(output, "output\n")
        # Check env contains token
        args, kwargs = mock_run.call_args
        self.assertIn("GH_TOKEN", kwargs['env'])
        self.assertEqual(kwargs['env']['GH_TOKEN'], "fake-token")

    @patch("subprocess.run")
    def test_run_gh_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, ["gh"], stderr="error")
        
        with self.assertRaises(GitHubClientError) as context:
            self.client._run_gh(["fail"])
        
        self.assertIn("gh command failed", str(context.exception))

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_generate_release_notes_targets_the_given_commit(self, mock_run_gh):
        mock_run_gh.return_value = "## What's Changed\n"

        self.client.generate_release_notes("r1.9", "r1.8", target_commitish="8a0a203")

        args = mock_run_gh.call_args[0][0]
        self.assertIn("target_commitish=8a0a203", args)
        self.assertIn("previous_tag_name=r1.8", args)

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_latest_release_tag(self, mock_run_gh):
        mock_run_gh.return_value = "r2.2\n"
        self.assertEqual(self.client.get_latest_release_tag(), "r2.2")
        self.assertIn("repos/owner/repo/releases/latest", mock_run_gh.call_args[0][0])

        mock_run_gh.side_effect = GitHubClientError("HTTP 404: Not Found")
        self.assertIsNone(self.client.get_latest_release_tag())

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_tag_exists(self, mock_run_gh):
        mock_run_gh.return_value = "refs/tags/r1.0"
        self.assertTrue(self.client.tag_exists("r1.0"))
        
        mock_run_gh.return_value = ""
        self.assertFalse(self.client.tag_exists("missing"))
        
        mock_run_gh.side_effect = GitHubClientError("Not found")
        self.assertFalse(self.client.tag_exists("error"))

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_list_branches(self, mock_run_gh):
        # Mock first call (list names)
        # Mock second call (get sha for branch 1)
        # Mock third call (get sha for branch 2)
        
        # It's easier to mock _run_gh to return different values based on calls
        # or just test the logic that parsing works.
        
        mock_run_gh.side_effect = [
            "branch1\nbranch2\n", # list
            "sha1\n", # sha for branch1
            "sha2\n"  # sha for branch2
        ]
        
        branches = self.client.list_branches()
        
        self.assertEqual(len(branches), 2)
        self.assertEqual(branches[0].name, "branch1")
        self.assertEqual(branches[0].sha, "sha1")
        self.assertEqual(branches[1].name, "branch2")
        self.assertEqual(branches[1].sha, "sha2")

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_delete_branch(self, mock_run_gh):
        mock_run_gh.return_value = ""
        self.assertTrue(self.client.delete_branch("feature"))

        # GitHub answers a DELETE on a missing ref with 422, not 404
        mock_run_gh.side_effect = GitHubClientError("gh: Reference does not exist (HTTP 422)")
        self.assertFalse(self.client.delete_branch("missing"))

        mock_run_gh.side_effect = GitHubClientError("gh: Not Found (HTTP 404)")
        self.assertFalse(self.client.delete_branch("missing"))

        mock_run_gh.side_effect = GitHubClientError("gh: Resource not accessible by integration (HTTP 403)")
        with self.assertRaises(GitHubClientError):
            self.client.delete_branch("protected")

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_file_content(self, mock_run_gh):
        mock_run_gh.return_value = "file content"
        content = self.client.get_file_content("path/to/file")
        self.assertEqual(content, "file content")
        
        mock_run_gh.side_effect = GitHubClientError("404 Not Found")
        content = self.client.get_file_content("missing")
        self.assertIsNone(content)

    @patch("release_automation.scripts.github_client.GitHubClient.get_file_content")
    def test_get_yaml_file(self, mock_get_file_content):
        mock_get_file_content.return_value = "version: 0.7.0-rc.1\n"

        content = self.client.get_yaml_file("VERSION.yaml", ref="r4.1")

        self.assertEqual(content, {"version": "0.7.0-rc.1"})
        mock_get_file_content.assert_called_once_with("VERSION.yaml", ref="r4.1")

    @patch("release_automation.scripts.github_client.GitHubClient.get_file_content")
    def test_get_yaml_file_invalid(self, mock_get_file_content):
        mock_get_file_content.return_value = "not: [valid"

        content = self.client.get_yaml_file("VERSION.yaml", ref="r4.1")

        self.assertIsNone(content)

    @patch("release_automation.scripts.github_client.GitHubClient.download_release_asset")
    @patch("release_automation.scripts.github_client.GitHubClient.get_file_content")
    def test_get_release_metadata_from_repo_tree(
        self, mock_get_file_content, mock_download_release_asset
    ):
        mock_get_file_content.return_value = (
            "repository:\n  release_tag: r4.1\napis:\n  - api_name: test-api\n"
            "    api_version: 1.0.0-rc.1\n"
        )

        metadata = self.client.get_release_metadata("r4.1")

        self.assertEqual(metadata["repository"]["release_tag"], "r4.1")
        self.assertEqual(metadata["apis"][0]["api_version"], "1.0.0-rc.1")
        mock_get_file_content.assert_called_once_with("release-metadata.yaml", ref="r4.1")
        mock_download_release_asset.assert_not_called()

    @patch("release_automation.scripts.github_client.GitHubClient.download_release_asset")
    @patch("release_automation.scripts.github_client.GitHubClient.get_file_content")
    def test_get_release_metadata_falls_back_to_release_asset(
        self, mock_get_file_content, mock_download_release_asset
    ):
        mock_get_file_content.return_value = None
        mock_download_release_asset.return_value = (
            "repository:\n  release_tag: r4.1\napis:\n  - api_name: test-api\n"
            "    api_version: 1.0.0-rc.1\n"
        )

        metadata = self.client.get_release_metadata("r4.1")

        self.assertEqual(metadata["apis"][0]["api_version"], "1.0.0-rc.1")
        mock_download_release_asset.assert_called_once_with("r4.1", "release-metadata.yaml")

    @patch("release_automation.scripts.github_client.GitHubClient.download_release_asset")
    @patch("release_automation.scripts.github_client.GitHubClient.get_file_content")
    def test_get_release_metadata_returns_none_for_invalid_yaml(
        self, mock_get_file_content, mock_download_release_asset
    ):
        mock_get_file_content.return_value = "just-a-string"

        metadata = self.client.get_release_metadata("r4.1")

        self.assertIsNone(metadata)
        mock_download_release_asset.assert_not_called()

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_create_issue(self, mock_run_gh):
        # create_issue returns a local dict from the URL output (no fetch-back)
        mock_run_gh.return_value = "https://github.com/owner/repo/issues/123\n"

        issue = self.client.create_issue("Title", "Body", ["label"])

        self.assertEqual(issue["number"], 123)
        self.assertEqual(issue["title"], "Title")
        self.assertEqual(issue["body"], "Body")
        self.assertEqual(issue["labels"], [{"name": "label"}])
        self.assertEqual(issue["html_url"], "https://github.com/owner/repo/issues/123")
        # Only one _run_gh call (create), no fetch-back
        self.assertEqual(mock_run_gh.call_count, 1)

    @patch("release_automation.scripts.github_client.time.sleep")
    def test_retry_on_not_found_succeeds_first_try(self, mock_sleep):
        fn = MagicMock(return_value="result")
        result = self.client.retry_on_not_found(fn)
        self.assertEqual(result, "result")
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("release_automation.scripts.github_client.time.sleep")
    def test_retry_on_not_found_retries_on_404(self, mock_sleep):
        fn = MagicMock(side_effect=[
            GitHubClientError("gh: Not Found (HTTP 404)"),
            "success"
        ])
        result = self.client.retry_on_not_found(fn, max_retries=3, delay=1.0)
        self.assertEqual(result, "success")
        self.assertEqual(fn.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)  # delay * (attempt+1) = 1.0 * 1

    @patch("release_automation.scripts.github_client.time.sleep")
    def test_retry_on_not_found_gives_up_after_max_retries(self, mock_sleep):
        fn = MagicMock(side_effect=GitHubClientError("HTTP 404"))
        with self.assertRaises(GitHubClientError):
            self.client.retry_on_not_found(fn, max_retries=3, delay=0.5)
        self.assertEqual(fn.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)  # retries 1 and 2, not after final

    @patch("release_automation.scripts.github_client.time.sleep")
    def test_retry_on_not_found_raises_non_404_immediately(self, mock_sleep):
        fn = MagicMock(side_effect=GitHubClientError("HTTP 500 Server Error"))
        with self.assertRaises(GitHubClientError):
            self.client.retry_on_not_found(fn, max_retries=3)
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_tag_sha_success(self, mock_run_gh):
        mock_run_gh.return_value = "abc123def456\n"
        sha = self.client.get_tag_sha("r4.1")
        self.assertEqual(sha, "abc123def456")

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_tag_sha_not_found(self, mock_run_gh):
        mock_run_gh.side_effect = GitHubClientError("404 Not Found")
        sha = self.client.get_tag_sha("missing")
        self.assertIsNone(sha)

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_tag_sha_empty_response(self, mock_run_gh):
        mock_run_gh.return_value = "\n"
        sha = self.client.get_tag_sha("r4.1")
        self.assertIsNone(sha)

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_create_branch_at_sha_success(self, mock_run_gh):
        mock_run_gh.return_value = '{"ref": "refs/heads/release/r4.1"}'
        result = self.client.create_branch_at_sha("release/r4.1", "abc123")
        self.assertTrue(result)
        mock_run_gh.assert_called_once()

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_create_branch_at_sha_already_exists(self, mock_run_gh):
        mock_run_gh.side_effect = GitHubClientError("422: Reference already exists")
        result = self.client.create_branch_at_sha("release/r4.1", "abc123")
        self.assertFalse(result)

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_create_branch_at_sha_api_error(self, mock_run_gh):
        mock_run_gh.side_effect = GitHubClientError("500: Internal server error")
        with self.assertRaises(GitHubClientError):
            self.client.create_branch_at_sha("release/r4.1", "abc123")

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_commit_files_adds_one_commit_on_the_branch_head(self, mock_run_gh):
        mock_run_gh.side_effect = ["head1\n", "tree1\n", "tree2\n", "commit2\n", "{}"]

        sha = self.client.commit_files(
            "maintenance/r1", {"CHANGELOG/CHANGELOG-r1.md": "# r1.8\n"}, "chore: set up"
        )

        self.assertEqual(sha, "commit2")
        calls = mock_run_gh.call_args_list
        self.assertIn("repos/owner/repo/git/ref/heads/maintenance/r1", calls[0].args[0])
        self.assertIn("repos/owner/repo/git/commits/head1", calls[1].args[0])
        self.assertEqual(json.loads(calls[2].kwargs["input"]), {
            "base_tree": "tree1",
            "tree": [{"path": "CHANGELOG/CHANGELOG-r1.md", "mode": "100644", "type": "blob", "content": "# r1.8\n"}],
        })
        self.assertEqual(json.loads(calls[3].kwargs["input"]),
                         {"message": "chore: set up", "tree": "tree2", "parents": ["head1"]})
        # A fast-forward of the branch: no force
        update = calls[4].args[0]
        self.assertIn("repos/owner/repo/git/refs/heads/maintenance/r1", update)
        self.assertIn("sha=commit2", update)
        self.assertIn("force=false", update)

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_commit_files_on_a_missing_branch_raises(self, mock_run_gh):
        mock_run_gh.side_effect = GitHubClientError("gh command failed: HTTP 404: Not Found")
        with self.assertRaises(GitHubClientError):
            self.client.commit_files("maintenance/r9", {"a": "b"}, "m")

    @patch("subprocess.run")
    def test_run_gh_passes_input_on_stdin(self, mock_run):
        mock_run.return_value = MagicMock(stdout="{}")
        self.client._run_gh(["api", "x", "--input", "-"], input='{"a": 1}')
        self.assertEqual(mock_run.call_args.kwargs["input"], '{"a": 1}')

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_find_open_pr(self, mock_run_gh):
        mock_run_gh.return_value = json.dumps([{"number": 7, "url": "https://github.com/owner/repo/pull/7"}])
        self.assertEqual(self.client.find_open_pr("sync-common/r4.3"), (7, "https://github.com/owner/repo/pull/7"))
        args = mock_run_gh.call_args[0][0]
        self.assertEqual(args[:2], ["pr", "list"])
        self.assertIn("--head", args)
        self.assertEqual(args[args.index("--head") + 1], "sync-common/r4.3")
        self.assertEqual(args[args.index("--state") + 1], "open")

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_find_open_pr_none(self, mock_run_gh):
        mock_run_gh.return_value = "[]"
        self.assertIsNone(self.client.find_open_pr("sync-common/r4.3"))

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_find_open_pr_api_error(self, mock_run_gh):
        mock_run_gh.side_effect = GitHubClientError("500")
        self.assertIsNone(self.client.find_open_pr("sync-common/r4.3"))

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_list_open_prs(self, mock_run_gh):
        mock_run_gh.return_value = json.dumps([
            {"number": 3, "headRefName": "sync-common/r4.2", "url": "u3"},
        ])
        self.assertEqual(self.client.list_open_prs(), [{"number": 3, "head": "sync-common/r4.2", "url": "u3"}])

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_create_pr(self, mock_run_gh):
        mock_run_gh.return_value = "https://github.com/owner/repo/pull/12\n"
        result = self.client.create_pr("T", "B", head="pr-to-main/r1.3", base="main")
        self.assertEqual(result, (12, "https://github.com/owner/repo/pull/12"))
        self.assertEqual(mock_run_gh.call_args[0][0], [
            "pr", "create", "--repo", "owner/repo", "--title", "T", "--body", "B",
            "--head", "pr-to-main/r1.3", "--base", "main",
        ])

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_add_pr_labels(self, mock_run_gh):
        self.client.add_pr_labels(12, ["post-release", "automated"])
        self.assertEqual(mock_run_gh.call_args[0][0], [
            "pr", "edit", "12", "--repo", "owner/repo",
            "--add-label", "post-release", "--add-label", "automated",
        ])

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_close_pr_with_comment(self, mock_run_gh):
        self.client.close_pr(3, comment="Superseded")
        self.assertEqual(mock_run_gh.call_args[0][0], [
            "pr", "close", "3", "--repo", "owner/repo", "--comment", "Superseded",
        ])

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_create_comment_returns_id(self, mock_run_gh):
        mock_run_gh.return_value = json.dumps({"id": 991, "body": "x"})
        self.assertEqual(self.client.create_comment(42, "hello"), 991)
        self.assertEqual(mock_run_gh.call_args[0][0], [
            "api", "repos/owner/repo/issues/42/comments", "-X", "POST", "-f", "body=hello",
        ])

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_update_comment(self, mock_run_gh):
        self.client.update_comment(991, "@user ok")
        self.assertEqual(mock_run_gh.call_args[0][0], [
            "api", "repos/owner/repo/issues/comments/991", "-X", "PATCH", "-f", "body=@user ok",
        ])

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_collaborator_permission(self, mock_run_gh):
        mock_run_gh.return_value = "maintain\n"
        self.assertEqual(self.client.get_collaborator_permission("alice"), "maintain")
        args = mock_run_gh.call_args[0][0]
        self.assertIn("repos/owner/repo/collaborators/alice/permission", args)

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_collaborator_permission_error_raises(self, mock_run_gh):
        mock_run_gh.side_effect = GitHubClientError("gh command failed: HTTP 502")
        with self.assertRaises(GitHubClientError):
            self.client.get_collaborator_permission("alice")

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_file_content_strict_returns_none_on_404(self, mock_run_gh):
        mock_run_gh.side_effect = GitHubClientError("gh command failed: HTTP 404: Not Found")
        self.assertIsNone(self.client.get_file_content("CODEOWNERS", strict=True))

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_file_content_strict_raises_on_other_errors(self, mock_run_gh):
        mock_run_gh.side_effect = GitHubClientError("gh command failed: HTTP 500")
        with self.assertRaises(GitHubClientError):
            self.client.get_file_content("CODEOWNERS", strict=True)

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_file_content_default_swallows_other_errors(self, mock_run_gh):
        mock_run_gh.side_effect = GitHubClientError("gh command failed: HTTP 500")
        self.assertIsNone(self.client.get_file_content("CODEOWNERS"))

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_create_release_draft(self, mock_run_gh):
        mock_run_gh.return_value = json.dumps({"id": 7, "html_url": "https://github.com/owner/repo/releases/tag/untagged-1"})
        result = self.client.create_release("r1.4", "release-snapshot/r1.4-abc1234", "r1.4", "## Release Notes", draft=True, prerelease=True)
        self.assertEqual(result["id"], 7)
        self.assertEqual(mock_run_gh.call_args[0][0], [
            "api", "repos/owner/repo/releases", "-X", "POST",
            "-f", "tag_name=r1.4", "-f", "target_commitish=release-snapshot/r1.4-abc1234",
            "-f", "name=r1.4", "-f", "body=## Release Notes",
            "-F", "draft=true", "-F", "prerelease=true",
        ])

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_create_release_published_latest(self, mock_run_gh):
        mock_run_gh.return_value = json.dumps({"id": 8, "html_url": "u"})
        self.client.create_release("r2.1", "b", "r2.1", "x", draft=False, prerelease=False, make_latest="true")
        self.assertEqual(mock_run_gh.call_args[0][0][-6:], [
            "-F", "draft=false", "-F", "prerelease=false", "-f", "make_latest=true",
        ])

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_delete_release(self, mock_run_gh):
        self.client.delete_release(7)
        self.assertEqual(mock_run_gh.call_args[0][0], ["api", "repos/owner/repo/releases/7", "-X", "DELETE"])

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_delete_tag(self, mock_run_gh):
        self.assertTrue(self.client.delete_tag("r1.4"))
        self.assertEqual(mock_run_gh.call_args[0][0], ["api", "repos/owner/repo/git/refs/tags/r1.4", "-X", "DELETE"])
        mock_run_gh.side_effect = GitHubClientError("gh command failed: HTTP 422: Reference does not exist")
        self.assertFalse(self.client.delete_tag("r1.4"))

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_delete_tag_raises_other_errors(self, mock_run_gh):
        mock_run_gh.side_effect = GitHubClientError("gh command failed: HTTP 500")
        with self.assertRaises(GitHubClientError):
            self.client.delete_tag("r1.4")

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_reopen_issue(self, mock_run_gh):
        self.client.reopen_issue(40)
        self.assertEqual(mock_run_gh.call_args[0][0], ["api", "repos/owner/repo/issues/40", "-X", "PATCH", "-f", "state=open"])

    @patch("release_automation.scripts.github_client.GitHubClient._run_gh")
    def test_get_branch_sha(self, mock_run_gh):
        mock_run_gh.return_value = "abc123\n"
        self.assertEqual(self.client.get_branch_sha("release-review/r1.4-abc1234"), "abc123")
        self.assertEqual(mock_run_gh.call_args[0][0], [
            "api", "repos/owner/repo/git/ref/heads/release-review/r1.4-abc1234", "--jq", ".object.sha",
        ])
        mock_run_gh.side_effect = GitHubClientError("gh command failed: HTTP 404: Not Found")
        self.assertIsNone(self.client.get_branch_sha("gone"))

if __name__ == '__main__':
    unittest.main()
