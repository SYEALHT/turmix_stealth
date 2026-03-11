"""
pipeline.py — The master pipeline. Wires together AppGenerator + GitHubPusher + VercelDeployer.
Both the CLI and Discord bot call this.

Pipeline Steps:
  1. Generate app files with AI (Pass 1: Plan, Pass 2: Generate)
  2. Validate & Fix code quality issues (Pass 3: Validate)
  3. Save files locally for inspection
  4. Push to GitHub
  5. Deploy to Vercel (optional)
"""

import sys
import os

# Make sure parent directory is on the path so imports work from any location
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config, Config
from core.app_generator import AppGenerator, GeneratedFile, _get_ai_client
from core.github_pusher import GitHubPusher
from core.file_writer import save_locally
from core.code_fixer import fix_files_with_ai


def run_pipeline(prompt: str, skip_validation: bool = False) -> dict:
    """
    Full pipeline: NLP prompt → Validate → GitHub private repo → Vercel live URL.
    
    Args:
        prompt: Plain-English app description
        skip_validation: If True, skip Pass 3 (code validation/fixing)
        
    Returns:
        dict with keys: repo_url, live_url, repo_name, description, how_to_run, tech_stack
    """
    # Validate secrets first
    Config.validate()

    print(f"\n{'='*60}")
    print(f"  🚀 AppBuilder Pipeline Starting")
    print(f"{'='*60}")
    print(f"  Prompt: {prompt[:120]}{'...' if len(prompt) > 120 else ''}")
    print(f"{'='*60}\n")

    # Step 1: Generate app with AI (Pass 1 + Pass 2)
    generator = AppGenerator()
    bundle = generator.generate(prompt)

    # Step 2: Validate & Fix (Pass 3) — check deprecated libs, unused imports
    raw_files = [{"path": f.path, "content": f.content} for f in bundle.files]
    
    if not skip_validation:
        print(f"\n{'='*60}")
        print(f"  🔍 Pass 3: Validating & Fixing Code Quality")
        print(f"{'='*60}\n")
        
        try:
            ai_client = _get_ai_client()
            fixed_files = fix_files_with_ai(raw_files, ai_client)
            
            # Update bundle with fixed files
            bundle.files = [GeneratedFile(path=f["path"], content=f["content"]) for f in fixed_files]
            raw_files = fixed_files
            
        except Exception as e:
            print(f"[Pipeline] ⚠️ Validation failed (non-fatal): {e}")
            print("[Pipeline] Continuing with original files...")
    
    # Step 3: Save files locally for inspection
    local_path = save_locally(bundle.repo_name, raw_files)

    # Step 4: Push to GitHub
    pusher = GitHubPusher()
    repo_url, repo_obj = pusher.push(bundle)

    # Step 5: Deploy to Vercel (optional — only if VERCEL_TOKEN is set)
    live_url = None
    vercel_token = getattr(config, "VERCEL_TOKEN", None) or os.getenv("VERCEL_TOKEN")
    if vercel_token:
        try:
            from core.vercel_deployer import VercelDeployer
            deployer = VercelDeployer()
            live_url = deployer.deploy(bundle.repo_name, raw_files, bundle.tech_stack)
            # Update GitHub repo description + homepage with the live URL
            pusher.update_description(repo_obj, live_url)
        except Exception as e:
            print(f"[Vercel] ⚠️ Deployment failed (non-fatal): {e}")
    else:
        print("[Vercel] ℹ️ VERCEL_TOKEN not set — skipping auto-deploy. Add it to .env to enable.")

    result = {
        "repo_url": repo_url,
        "live_url": live_url,
        "repo_name": bundle.repo_name,
        "description": bundle.description,
        "how_to_run": bundle.how_to_run,
        "tech_stack": bundle.tech_stack,
        "file_count": len(bundle.files),
        "tokens_used": bundle.__dict__.get("tokens_used"),
        "local_path": str(local_path),
    }

    print(f"\n{'='*60}")
    print(f"  ✅ DONE! Your private repo is live:")
    print(f"  GitHub: {repo_url}")
    if live_url:
        print(f"  Vercel: {live_url}")
    print(f"  Local:  {local_path}")
    print(f"{'='*60}\n")

    return result
