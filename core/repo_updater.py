"""
repo_updater.py — Updates an existing GitHub repo based on a plain-English instruction.

Pipeline:
  1. Fetch current file list from the GitHub repo.
  2. Ask AI to produce a JSON plan of which files to create / modify / delete.
  3. For each file to change, generate new content with full context of what changed.
  4. Push changes via GitHubPusher.update_files().
"""

import sys
import os
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from core.app_generator import _get_ai_client
from core.github_pusher import GitHubPusher
from github import Auth, Github, GithubException


UPDATE_PLAN_PROMPT = """You are an expert software engineer tasked with updating an existing project.

The user wants to make changes to the repository. Your job is to return a JSON plan listing exactly which files need to be created, modified, or deleted.

OUTPUT FORMAT (strict JSON, no markdown):
{
  "summary": "One-line summary of the changes being made",
  "files_to_create": [
    {"path": "new_file.py", "description": "What this new file does"}
  ],
  "files_to_modify": [
    {"path": "existing_file.py", "description": "What to change in this file"}
  ],
  "files_to_delete": [
    "path/to/file.py"
  ]
}

RULES:
1. Only include files that ACTUALLY need to change for this update.
2. Be conservative — don't regenerate files that don't need changing.
3. If a file doesn't exist in the repo but is needed, put it in files_to_create.
4. Return an empty list [] for any category with no changes.
5. Do NOT write any code in this response. Only the plan.
"""

FILE_UPDATE_PROMPT = """You are an expert developer updating an existing project.

Current file: {file_path}
Existing content:
```
{existing_content}
```

User instruction: {instruction}
Change description: {change_description}

Rules:
- Output ONLY the complete updated file content. No explanations, no markdown fences.
- Preserve all existing functionality unless the instruction says to remove it.
- Apply the requested changes cleanly and completely.
- Keep the same code style, indentation, and conventions as the existing code.
"""

FILE_CREATE_PROMPT = """You are an expert developer creating a new file for an existing project.

New file: {file_path}
Description: {change_description}
User instruction: {instruction}
Existing files in the repo: {file_list}

Rules:
- Output ONLY the complete file content. No explanations, no markdown fences.
- Make it production-ready, matching the style of the existing project.
"""


class RepoUpdater:
    """Fetches a repo, plans changes with AI, generates updated content, and pushes."""

    def __init__(self):
        auth = Auth.Token(config.GITHUB_TOKEN)
        self.gh = Github(auth=auth)
        self.user = self.gh.get_user()
        self.ai = _get_ai_client()
        self.pusher = GitHubPusher()

    def run(self, repo_name_or_url: str, instruction: str) -> dict:
        """
        Full update pipeline. Accepts:
          - A bare repo name:           "todo-app"
          - A full GitHub URL:          "https://github.com/user/todo-app"
          - A GitHub URL with extras:   "https://github.com/user/todo-app/tree/main"
        Returns dict with: repo_url, summary, files_changed list.
        """
        # ── Parse repo identifier ────────────────────────────────────────────
        repo_input = repo_name_or_url.strip().rstrip("/")
        full_name = None

        if "github.com" in repo_input:
            # Extract owner/repo from URL like https://github.com/owner/repo[/...]
            import re as _re
            m = _re.search(r"github\.com/([^/]+/[^/]+)", repo_input)
            if m:
                full_name = m.group(1).split("/tree/")[0].split("/blob/")[0]
            else:
                raise ValueError(f"❌ Couldn't parse a GitHub repo from: `{repo_input}`")
        else:
            # Bare name — prepend the configured GitHub username
            repo_name = repo_input.split("/")[-1]  # handle 'user/repo' too
            full_name = f"{config.GITHUB_USERNAME}/{repo_name}"

        repo_name = full_name.split("/")[-1]
        print(f"[RepoUpdater] 🔍 Looking up repo: {full_name}")
        try:
            repo = self.gh.get_repo(full_name)
        except GithubException as e:
            raise ValueError(f"❌ Repo `{full_name}` not found or not accessible: {e}")

        # ── Step 2: Fetch all file paths (shallow list) ──────────────────────
        print(f"[RepoUpdater] 📂 Fetching file tree...")
        try:
            contents = repo.get_git_tree("main", recursive=True)
            all_files = [f.path for f in contents.tree if f.type == "blob"]
        except GithubException:
            # Fallback to root listing
            all_files = [c.path for c in repo.get_contents("")]
        print(f"[RepoUpdater]    Found {len(all_files)} files: {', '.join(all_files[:10])}")

        # ── Step 3: AI plans which files to change ───────────────────────────
        print(f"[RepoUpdater] 🧠 Planning changes for: \"{instruction[:80]}\"")
        plan_prompt = (
            f"Existing repo files: {json.dumps(all_files)}\n\n"
            f"User instruction: {instruction}\n\n"
            f"Plan which files to create, modify, or delete."
        )
        plan_text, _ = self.ai._call(
            prompt=plan_prompt,
            system=UPDATE_PLAN_PROMPT,
            json_mode=True,
            max_tokens=2048,
        )
        plan_text = re.sub(r"^```(?:json)?\s*", "", plan_text, flags=re.MULTILINE)
        plan_text = re.sub(r"\s*```$", "", plan_text, flags=re.MULTILINE).strip()

        try:
            plan = json.loads(plan_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"❌ Failed to parse update plan: {e}\nRaw: {plan_text[:300]}")

        summary = plan.get("summary", instruction[:100])
        to_create = plan.get("files_to_create", [])
        to_modify = plan.get("files_to_modify", [])
        to_delete = plan.get("files_to_delete", [])

        print(f"[RepoUpdater] ✅ Plan: create={len(to_create)}, modify={len(to_modify)}, delete={len(to_delete)}")

        file_list_str = "\n".join(all_files)
        files_changed = []

        # ── Step 4a: Modify existing files ───────────────────────────────────
        for entry in to_modify:
            path = entry.get("path", "")
            desc = entry.get("description", "")
            print(f"[RepoUpdater] ✏️  Modifying: {path}")

            # Fetch existing content
            existing = ""
            try:
                fc = repo.get_contents(path)
                existing = fc.decoded_content.decode("utf-8")
            except Exception:
                existing = "# (could not fetch existing content)"

            # Truncate for very large files
            if len(existing) > 8000:
                existing = existing[:8000] + "\n# ... (truncated)"

            prompt = FILE_UPDATE_PROMPT.format(
                file_path=path,
                existing_content=existing,
                instruction=instruction,
                change_description=desc,
            )
            try:
                content, _ = self.ai._call(
                    prompt=prompt,
                    system=f"You are an expert developer. Output ONLY complete raw file content, no markdown fences.",
                    json_mode=False,
                    max_tokens=8000,
                )
                content = re.sub(r"^```[\w]*\n?", "", content, flags=re.MULTILINE)
                content = re.sub(r"\n?```$", "", content, flags=re.MULTILINE).strip()
                files_changed.append({"path": path, "content": content, "action": "modify"})
                print(f"[RepoUpdater]    ✅ {path} ({len(content)} chars)")
            except Exception as e:
                print(f"[RepoUpdater]    ⚠️ Failed to generate {path}: {e}")

        # ── Step 4b: Create new files ─────────────────────────────────────────
        for entry in to_create:
            path = entry.get("path", "")
            desc = entry.get("description", "")
            print(f"[RepoUpdater] ➕ Creating: {path}")

            prompt = FILE_CREATE_PROMPT.format(
                file_path=path,
                change_description=desc,
                instruction=instruction,
                file_list=file_list_str[:2000],
            )
            try:
                content, _ = self.ai._call(
                    prompt=prompt,
                    system=f"You are an expert developer. Output ONLY complete raw file content, no markdown fences.",
                    json_mode=False,
                    max_tokens=8000,
                )
                content = re.sub(r"^```[\w]*\n?", "", content, flags=re.MULTILINE)
                content = re.sub(r"\n?```$", "", content, flags=re.MULTILINE).strip()
                files_changed.append({"path": path, "content": content, "action": "create"})
                print(f"[RepoUpdater]    ✅ {path} ({len(content)} chars)")
            except Exception as e:
                print(f"[RepoUpdater]    ⚠️ Failed to create {path}: {e}")

        # ── Step 5: Push all changes ──────────────────────────────────────────
        if not files_changed and not to_delete:
            raise ValueError("❌ AI decided no files need changing for that instruction.")

        print(f"[RepoUpdater] 🚀 Pushing {len(files_changed)} file(s) + {len(to_delete)} deletion(s)...")
        self.pusher.update_files(repo, files_changed, to_delete, commit_message=f"fix: {summary[:72]}")

        print(f"[RepoUpdater] 🎉 Done! Repo updated: {repo.html_url}")
        return {
            "repo_url": repo.html_url,
            "repo_name": repo_name,
            "summary": summary,
            "files_changed": files_changed,
            "files_deleted": to_delete,
        }
