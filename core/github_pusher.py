"""
github_pusher.py — Creates a private GitHub repo and pushes all generated files.
Uses the PyGithub library + GitHub REST API.
"""

import base64
import time
from github import Github, Auth, GithubException
from core.app_generator import AppBundle
from config import config


class GitHubPusher:
    def __init__(self):
        auth = Auth.Token(config.GITHUB_TOKEN)
        self.gh = Github(auth=auth)
        self.user = self.gh.get_user()

    def push(self, bundle: AppBundle) -> str:
        """
        Create a private repo and push all files from AppBundle in a single commit.
        
        Args:
            bundle: The AppBundle to push
            
        Returns:
            The URL of the newly created GitHub repo
        """
        repo_name = self._safe_repo_name(bundle.repo_name)
        
        print(f"[GitHub] Creating private repo: {config.GITHUB_USERNAME}/{repo_name}")
        
        # Create the private repo
        try:
            repo = self.user.create_repo(
                name=repo_name,
                description=bundle.description,
                private=True,
                auto_init=False,  # We'll push files ourselves
            )
        except GithubException as e:
            if "already exists" in str(e):
                # Append timestamp to avoid conflicts
                repo_name = f"{repo_name}-{int(time.time())}"
                print(f"[GitHub] Name taken, using: {repo_name}")
                repo = self.user.create_repo(
                    name=repo_name,
                    description=bundle.description,
                    private=True,
                    auto_init=False,
                )
            else:
                raise

        print(f"[GitHub] ✅ Repo created: {repo.html_url}")

        # Push files one by one via GitHub Contents API (no git needed locally)
        print(f"[GitHub] Pushing {len(bundle.files)} files...")
        
        for gen_file in bundle.files:
            try:
                content_bytes = gen_file.content.encode("utf-8")
                repo.create_file(
                    path=gen_file.path,
                    message=f"feat: initial generated app — {gen_file.path}",
                    content=content_bytes,
                    branch="main",
                )
                print(f"[GitHub]   ✅ {gen_file.path}")
            except GithubException as e:
                print(f"[GitHub]   ⚠️  Skipped {gen_file.path}: {e.data.get('message', str(e))}")

        print(f"[GitHub] 🎉 All files pushed to: {repo.html_url}\")")
        return repo.html_url, repo

    def update_description(self, repo, live_url: str):
        """Update the repo description and homepage URL with the Vercel live URL."""
        try:
            repo.edit(
                description=f"{repo.description} | 🚀 Live: {live_url}",
                homepage=live_url,
            )
            print(f"[GitHub] ✅ Repo description updated with live URL: {live_url}")
        except Exception as e:
            print(f"[GitHub] ⚠️ Failed to update repo description: {e}")

    def update_files(self, repo, files: list, files_to_delete: list = None, commit_message: str = "fix: update files") -> None:
        """
        Update or create files in an existing repo.
        
        Args:
            repo: PyGithub repo object
            files: list of {"path": str, "content": str, "action": "modify"|"create"}
            files_to_delete: list of file paths to delete
            commit_message: commit message prefix
        """
        print(f"[GitHub] 📝 Updating {len(files)} file(s) in {repo.full_name}...")

        for file_dict in files:
            path = file_dict["path"]
            content = file_dict["content"]
            content_bytes = content.encode("utf-8")

            try:
                # Try to get existing file SHA (needed for updates)
                existing = repo.get_contents(path)
                repo.update_file(
                    path=path,
                    message=f"{commit_message} — {path}",
                    content=content_bytes,
                    sha=existing.sha,
                    branch="main",
                )
                print(f"[GitHub]   ✅ Updated: {path}")
            except GithubException as e:
                if e.status == 404:
                    # File doesn't exist yet — create it
                    repo.create_file(
                        path=path,
                        message=f"{commit_message} — {path} (new)",
                        content=content_bytes,
                        branch="main",
                    )
                    print(f"[GitHub]   ➕ Created: {path}")
                else:
                    print(f"[GitHub]   ⚠️  Failed to update {path}: {e}")

        # Handle deletions
        for path in (files_to_delete or []):
            try:
                existing = repo.get_contents(path)
                repo.delete_file(
                    path=path,
                    message=f"{commit_message} — remove {path}",
                    sha=existing.sha,
                    branch="main",
                )
                print(f"[GitHub]   🗑️  Deleted: {path}")
            except GithubException as e:
                print(f"[GitHub]   ⚠️  Failed to delete {path}: {e}")

        print(f"[GitHub] ✅ Repo update complete: {repo.html_url}")

    def _safe_repo_name(self, name: str) -> str:
        """Ensure repo name is valid for GitHub (alphanumeric + hyphens)."""
        import re
        # Replace spaces and underscores with hyphens
        name = name.replace(" ", "-").replace("_", "-")
        # Remove any char that isn't alphanumeric or hyphen
        name = re.sub(r"[^a-zA-Z0-9\-]", "", name)
        # Trim leading/trailing hyphens
        name = name.strip("-")
        return name.lower() or "generated-app"

