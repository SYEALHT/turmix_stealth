"""
file_writer.py — Saves generated files locally for inspection AND to temp dir.

This allows users to:
1. See exactly what's being generated in ./output/
2. Debug issues without checking GitHub
3. Have a local copy of their apps
"""

import os
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from core.app_generator import AppBundle

# Persistent output directory relative to appbuilder/
OUTPUT_DIR = Path(__file__).parent.parent / "output"


class FileWriter:
    def write_to_temp(self, bundle: AppBundle) -> str:
        """
        Write all files in an AppBundle to a fresh temp directory.
        
        Args:
            bundle: The AppBundle to write
            
        Returns:
            Path to the temp directory containing all files
        """
        # Create a temp dir; caller is responsible for cleanup
        tmp_dir = tempfile.mkdtemp(prefix=f"appbuilder_{bundle.repo_name}_")
        print(f"[FileWriter] Writing {len(bundle.files)} files to: {tmp_dir}")

        for gen_file in bundle.files:
            dest_path = Path(tmp_dir) / gen_file.path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_text(gen_file.content, encoding="utf-8")
            print(f"[FileWriter]   ✍  {gen_file.path}")

        print(f"[FileWriter] ✅ Done writing files.")
        return tmp_dir

    def cleanup(self, tmp_dir: str):
        """Remove the temp directory after pushing to GitHub."""
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"[FileWriter] 🧹 Cleaned up: {tmp_dir}")


def save_locally(repo_name: str, files: List[Dict[str, str]]) -> Path:
    """
    Save generated files to ./output/<repo_name>_<timestamp>/ for inspection.
    
    Args:
        repo_name: Name of the repo (used as folder name)
        files: List of {"path": str, "content": str}
        
    Returns:
        Path to the output directory
    """
    # Create timestamped folder to avoid conflicts
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"{repo_name}_{timestamp}"
    
    # Ensure output directory exists
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"\n[FileWriter] 📁 Saving files locally to: {output_path}")
    
    saved_count = 0
    for file_dict in files:
        file_path = output_path / file_dict["path"]
        
        # Create subdirectories if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        try:
            file_path.write_text(file_dict["content"], encoding="utf-8")
            print(f"[FileWriter]   ✅ {file_dict['path']}")
            saved_count += 1
        except Exception as e:
            print(f"[FileWriter]   ⚠️ Failed to save {file_dict['path']}: {e}")
    
    # Create a manifest file
    manifest_content = f"""# Generated App: {repo_name}
Generated at: {datetime.now().isoformat()}
Files: {len(files)}

## File List:
"""
    for file_dict in files:
        manifest_content += f"- {file_dict['path']}\n"
    
    (output_path / "_MANIFEST.md").write_text(manifest_content, encoding="utf-8")
    
    print(f"[FileWriter] 🎉 Saved {saved_count}/{len(files)} files locally!")
    print(f"[FileWriter] 📂 View at: {output_path}\n")
    
    return output_path


def get_latest_output(repo_name: str = None) -> Path | None:
    """
    Get the most recent output directory.
    
    Args:
        repo_name: If provided, filter by repo name prefix
        
    Returns:
        Path to the most recent output folder, or None
    """
    if not OUTPUT_DIR.exists():
        return None
    
    folders = sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if repo_name:
        folders = [f for f in folders if f.name.startswith(repo_name)]
    
    return folders[0] if folders else None


def cleanup_old_outputs(keep_count: int = 10) -> int:
    """
    Delete old output folders, keeping only the most recent ones.
    
    Args:
        keep_count: Number of recent outputs to keep
        
    Returns:
        Number of folders deleted
    """
    if not OUTPUT_DIR.exists():
        return 0
    
    folders = sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    
    deleted = 0
    for folder in folders[keep_count:]:
        try:
            shutil.rmtree(folder)
            deleted += 1
        except Exception:
            pass
    
    return deleted
