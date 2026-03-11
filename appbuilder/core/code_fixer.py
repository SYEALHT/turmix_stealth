"""
code_fixer.py — Uses AI to fix code quality issues found by the validator.

This is Pass 3 of the generation pipeline:
  Pass 1: Plan (file manifest)
  Pass 2: Generate (raw file content)
  Pass 3: Validate & Fix (this module)
"""

import re
from typing import List, Dict, Optional
from core.code_validator import validate_files, print_validation_report, DEPRECATED_PACKAGES, MODERN_ALTERNATIVES


FIX_PROMPT_TEMPLATE = """You are a code quality expert. Fix the following issues in this file.

FILE: {file_path}
CURRENT CONTENT:
```
{content}
```

ISSUES TO FIX:
{issues_list}

RULES:
1. Output ONLY the fixed file content — no explanations, no markdown fences.
2. Remove ALL unused imports.
3. Replace ALL deprecated packages with modern alternatives.
4. Keep the code functionality identical — only fix the issues listed.
5. Preserve all comments and docstrings.
6. Do NOT add new features or change logic.
"""


def fix_files_with_ai(files: List[Dict[str, str]], ai_client) -> List[Dict[str, str]]:
    """
    Validate files and use AI to fix any issues.
    
    Args:
        files: List of {"path": str, "content": str}
        ai_client: An AI client instance (GeminiClient, GroqClient, or GitHubModelsClient)
        
    Returns:
        List of fixed files
    """
    # First, validate all files
    issues = validate_files(files)
    
    if not issues:
        print("[CodeFixer] ✅ No issues found — files are clean!")
        return files
    
    print_validation_report(issues)
    
    # Fix files with issues
    fixed_files = []
    files_by_path = {f["path"]: f for f in files}
    
    for file_dict in files:
        path = file_dict["path"]
        content = file_dict["content"]
        
        if path not in issues:
            # No issues — keep as-is
            fixed_files.append(file_dict)
            continue
        
        file_issues = issues[path]
        print(f"[CodeFixer] 🔧 Fixing {len(file_issues)} issue(s) in {path}...")
        
        # For simple cases, fix directly without AI
        if can_fix_without_ai(path, file_issues):
            fixed_content = fix_without_ai(content, file_issues, path)
            fixed_files.append({"path": path, "content": fixed_content})
            print(f"[CodeFixer]    ✅ Fixed {path} (direct fix)")
            continue
        
        # For complex cases, use AI
        issues_text = format_issues_for_prompt(file_issues)
        
        prompt = FIX_PROMPT_TEMPLATE.format(
            file_path=path,
            content=content,
            issues_list=issues_text,
        )
        
        try:
            fixed_content, _ = ai_client._call(
                prompt=prompt,
                system="You are a code quality fixer. Output ONLY the fixed code, nothing else.",
                json_mode=False,
                max_tokens=16000,
            )
            
            # Strip markdown fences if AI added them
            fixed_content = re.sub(r"^```[\w]*\n?", "", fixed_content, flags=re.MULTILINE)
            fixed_content = re.sub(r"\n?```$", "", fixed_content, flags=re.MULTILINE).strip()
            
            fixed_files.append({"path": path, "content": fixed_content})
            print(f"[CodeFixer]    ✅ Fixed {path} (AI fix)")
            
        except Exception as e:
            print(f"[CodeFixer]    ⚠️ AI fix failed for {path}: {e}")
            # Fall back to original + direct fixes
            fixed_content = fix_without_ai(content, file_issues, path)
            fixed_files.append({"path": path, "content": fixed_content})
    
    # Re-validate to confirm fixes
    print("\n[CodeFixer] 🔍 Re-validating fixed files...")
    remaining_issues = validate_files(fixed_files)
    
    if remaining_issues:
        remaining_count = sum(len(i) for i in remaining_issues.values())
        print(f"[CodeFixer] ⚠️ {remaining_count} issue(s) remain after fixing")
    else:
        print("[CodeFixer] ✅ All issues resolved!")
    
    return fixed_files


def can_fix_without_ai(path: str, issues: List[Dict]) -> bool:
    """Check if issues can be fixed with simple regex without AI."""
    for issue in issues:
        issue_type = issue.get("type", "")
        # Unused imports and deprecated packages in requirements.txt can be fixed directly
        if issue_type not in ("unused_import", "deprecated_pattern"):
            if path != "requirements.txt":
                return False
    return True


def fix_without_ai(content: str, issues: List[Dict], path: str) -> str:
    """Fix simple issues directly without AI."""
    lines = content.split("\n")
    
    if path == "requirements.txt":
        return fix_requirements_txt(content, issues)
    
    # Fix Python files
    lines_to_remove = set()
    
    for issue in issues:
        if issue.get("type") == "unused_import":
            line_num = issue["line"] - 1  # Convert to 0-indexed
            if 0 <= line_num < len(lines):
                line = lines[line_num]
                import_name = issue["name"]
                
                # Check if it's a single import or part of multi-import
                if f"import {import_name}" in line and "," not in line:
                    lines_to_remove.add(line_num)
                elif "," in line:
                    # Multi-import: from x import a, b, c
                    # Remove just the unused one
                    new_line = re.sub(rf',\s*{re.escape(import_name)}(?=\s*[,\)]|$)', '', line)
                    new_line = re.sub(rf'{re.escape(import_name)}\s*,\s*', '', new_line)
                    lines[line_num] = new_line
    
    # Remove marked lines
    fixed_lines = [
        line for i, line in enumerate(lines)
        if i not in lines_to_remove
    ]
    
    return "\n".join(fixed_lines)


def fix_requirements_txt(content: str, issues: List[Dict]) -> str:
    """Fix deprecated packages in requirements.txt."""
    lines = content.split("\n")
    
    for issue in issues:
        line_num = issue.get("line", 0) - 1
        if 0 <= line_num < len(lines):
            old_pkg = issue.get("package", "")
            replacement = issue.get("replacement", "")
            
            if replacement and replacement != "N/A":
                # Get version specifier if any
                old_line = lines[line_num]
                version_match = re.search(r'[><=~!]+[\d.]+', old_line)
                version = version_match.group(0) if version_match else ""
                
                # Handle multiple replacement options
                new_pkg = replacement.split(" or ")[0].strip()
                lines[line_num] = f"{new_pkg}{version}"
                print(f"[CodeFixer]    Replaced {old_pkg} → {new_pkg}")
            elif replacement == "N/A":
                # Package not needed — comment it out
                lines[line_num] = f"# {lines[line_num]}  # Not needed in Python 3.9+"
    
    return "\n".join(lines)


def format_issues_for_prompt(issues: List[Dict]) -> str:
    """Format issues list for the AI prompt."""
    parts = []
    for issue in issues:
        if issue.get("type") == "unused_import":
            parts.append(f"- Line {issue['line']}: Remove unused import '{issue['name']}'")
        elif issue.get("type") == "deprecated_import":
            parts.append(f"- Line {issue['line']}: Replace deprecated '{issue['package']}' with '{issue['replacement']}' ({issue['reason']})")
        elif issue.get("type") == "deprecated_pattern":
            parts.append(f"- Line {issue['line']}: {issue['suggestion']}")
        elif issue.get("package"):
            parts.append(f"- Replace '{issue['package']}' with '{issue['replacement']}' ({issue['reason']})")
    return "\n".join(parts)
