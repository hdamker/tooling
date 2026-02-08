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
        # First call creates issue and returns URL
        # Second call gets issue details
        
        mock_run_gh.side_effect = [
            "https://github.com/owner/repo/issues/123\n", # create output
            json.dumps({"number": 123, "title": "Title", "html_url": "url", "state": "open"}) # get_issue output
        ]
        
        issue = self.client.create_issue("Title", "Body", ["label"])
        
        self.assertEqual(issue["number"], 123)
        self.assertEqual(issue["title"], "Title")

if __name__ == '__main__':
    unittest.main()
