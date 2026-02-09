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
    def test_get_file_content(self, mock_run_gh):
        mock_run_gh.return_value = "file content"
        content = self.client.get_file_content("path/to/file")
        self.assertEqual(content, "file content")
        
        mock_run_gh.side_effect = GitHubClientError("404 Not Found")
        content = self.client.get_file_content("missing")
        self.assertIsNone(content)

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

if __name__ == '__main__':
    unittest.main()
