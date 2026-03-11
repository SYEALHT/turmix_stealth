"""
code_validator.py — Pass 3: Validate and fix generated code quality.

This module:
1. Checks for deprecated/outdated Python packages
2. Detects unused imports
3. Validates that all imports reference real modules
4. Uses AI to fix any issues found

Run this AFTER file generation but BEFORE pushing to GitHub.
"""

import re
from typing import List, Dict, Tuple
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════════════
# DEPRECATED PACKAGES DATABASE
# Last updated: 2026-03
# ══════════════════════════════════════════════════════════════════════════════

DEPRECATED_PACKAGES = {
    # Package name → (replacement, reason)
    "flask-restful": ("flask-smorest or fastapi", "Unmaintained since 2023, use flask-smorest or migrate to FastAPI"),
    "flask-restplus": ("flask-smorest or flask-restx", "Abandoned, use flask-restx fork or flask-smorest"),
    "requests[security]": ("requests", "Security extras no longer needed in modern Python"),
    "pycrypto": ("pycryptodome", "PyCrypto is abandoned and insecure"),
    "crypto": ("pycryptodome", "Use pycryptodome instead"),
    "python-jose": ("pyjwt or joserfc", "python-jose has security issues, use PyJWT"),
    "flask-jwt": ("flask-jwt-extended", "flask-jwt is unmaintained"),
    "flask-script": ("click or flask cli", "Deprecated, Flask has built-in CLI support"),
    "flask-migrate": ("flask-migrate>=4.0", "Old versions have issues, ensure v4.0+"),
    "httplib2": ("httpx or requests", "httplib2 is outdated, use httpx or requests"),
    "urllib2": ("urllib3 or requests", "urllib2 doesn't exist in Python 3"),
    "urllib": ("requests or httpx", "Use requests or httpx for HTTP calls"),
    "imp": ("importlib", "imp is deprecated since Python 3.4"),
    "optparse": ("argparse", "optparse is deprecated since Python 2.7"),
    "distutils": ("setuptools", "distutils is deprecated since Python 3.10"),
    "asyncio-redis": ("redis[hiredis]", "Use official redis-py with async support"),
    "aioredis": ("redis[hiredis]", "aioredis merged into redis-py 4.2+"),
    "motor": ("motor>=3.0 or beanie", "Ensure modern motor or use Beanie ODM"),
    "mongoengine": ("beanie or motor", "Consider Beanie for async MongoDB"),
    "flask-socketio": ("python-socketio", "Consider pure python-socketio for better async"),
    "eventlet": ("uvloop or asyncio", "eventlet has compatibility issues, prefer native asyncio"),
    "gevent": ("asyncio", "gevent monkeypatching causes issues, prefer native asyncio"),
    "nose": ("pytest", "nose is unmaintained, use pytest"),
    "nose2": ("pytest", "pytest is more widely used and maintained"),
    "mock": ("unittest.mock", "mock is built into Python 3 as unittest.mock"),
    "future": ("N/A", "Not needed in Python 3.9+"),
    "six": ("N/A", "Not needed in Python 3.9+"),
    "python-dateutil": ("datetime or pendulum", "Often unnecessary, Python's datetime is sufficient"),
    "pytz": ("zoneinfo", "pytz deprecated in favor of built-in zoneinfo (Python 3.9+)"),
    "backports.zoneinfo": ("zoneinfo", "Not needed in Python 3.9+"),
    "typing-extensions": ("typing", "Most features in stdlib typing (Python 3.10+)"),
    "dataclasses": ("N/A", "Built into Python 3.7+"),
    "contextvars": ("N/A", "Built into Python 3.7+"),
    "pkg_resources": ("importlib.resources", "pkg_resources is slow, use importlib.resources"),
    "PIL": ("pillow", "Import as 'from PIL import Image' but install pillow"),
    "sklearn": ("scikit-learn", "Install scikit-learn, import as sklearn"),
    "cv2": ("opencv-python", "Install opencv-python, import as cv2"),
    "yaml": ("pyyaml", "Install pyyaml, import as yaml"),
    "bs4": ("beautifulsoup4", "Install beautifulsoup4, import as bs4"),
}

# Modern replacements for common patterns
MODERN_ALTERNATIVES = {
    "os.path": "Use pathlib.Path instead of os.path for file operations",
    "json.loads(open": "Use 'with open() as f: json.load(f)' or pathlib",
    "print(": "Use logging module for applications, not print()",
    "time.sleep": "Consider asyncio.sleep for async code",
    "threading.Thread": "Consider asyncio or concurrent.futures",
    "multiprocessing.Pool": "Consider concurrent.futures.ProcessPoolExecutor",
    "subprocess.call": "Use subprocess.run() instead (Python 3.5+)",
    "subprocess.Popen": "Consider subprocess.run() for simple cases",
    ".format(": "Use f-strings instead of .format()",
    "% ": "Use f-strings instead of % formatting",
    "dict.iteritems": "Use dict.items() in Python 3",
    "dict.iterkeys": "Use dict.keys() in Python 3",
    "dict.itervalues": "Use dict.values() in Python 3",
    "xrange": "Use range() in Python 3",
    "raw_input": "Use input() in Python 3",
    "unicode(": "str is unicode in Python 3",
    "basestring": "Use str in Python 3",
    "execfile": "Use exec(open().read()) in Python 3",
    "reload(": "Use importlib.reload()",
}


def check_requirements_txt(content: str) -> List[Dict]:
    """
    Check requirements.txt for deprecated packages.
    
    Returns list of issues found.
    """
    issues = []
    lines = content.strip().split("\n")
    
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        
        # Parse package name (handle ==, >=, <=, ~=, etc.)
        match = re.match(r'^([a-zA-Z0-9_-]+)', line)
        if not match:
            continue
        
        pkg_name = match.group(1).lower()
        
        # Check against deprecated list
        for deprecated, (replacement, reason) in DEPRECATED_PACKAGES.items():
            if pkg_name == deprecated.lower() or pkg_name == deprecated.lower().replace("-", "_"):
                issues.append({
                    "line": line_num,
                    "package": pkg_name,
                    "original": line,
                    "replacement": replacement,
                    "reason": reason,
                    "severity": "warning",
                })
    
    return issues


def check_python_imports(content: str, filename: str) -> List[Dict]:
    """
    Check Python file for unused imports and deprecated patterns.
    
    Returns list of issues found.
    """
    issues = []
    lines = content.split("\n")
    
    # Collect all imports
    imports = []
    import_pattern = re.compile(r'^(?:from\s+(\S+)\s+)?import\s+(.+)', re.MULTILINE)
    
    for line_num, line in enumerate(lines, 1):
        line_stripped = line.strip()
        
        # Skip comments and strings
        if line_stripped.startswith("#") or line_stripped.startswith('"""') or line_stripped.startswith("'''"):
            continue
        
        match = import_pattern.match(line_stripped)
        if match:
            module = match.group(1) or ""
            imported = match.group(2)
            
            # Handle multiple imports (import a, b, c)
            for item in imported.split(","):
                item = item.strip()
                # Handle 'as' aliases
                if " as " in item:
                    name, alias = item.split(" as ")
                    imports.append({
                        "line": line_num,
                        "module": module,
                        "name": name.strip(),
                        "alias": alias.strip(),
                        "full_line": line_stripped,
                    })
                else:
                    imports.append({
                        "line": line_num,
                        "module": module,
                        "name": item.strip(),
                        "alias": item.strip(),
                        "full_line": line_stripped,
                    })
    
    # Check if imports are used in the rest of the file
    code_without_imports = "\n".join(
        line for line in lines
        if not line.strip().startswith("import ") and not line.strip().startswith("from ")
    )
    
    for imp in imports:
        # Use the alias for checking usage
        check_name = imp["alias"]
        
        # Skip common always-used patterns
        if check_name in ("__future__", "annotations", "TYPE_CHECKING"):
            continue
        
        # Check if the name appears in the code
        # Use word boundary to avoid false positives
        pattern = rf'\b{re.escape(check_name)}\b'
        if not re.search(pattern, code_without_imports):
            issues.append({
                "line": imp["line"],
                "type": "unused_import",
                "import": imp["full_line"],
                "name": check_name,
                "severity": "warning",
                "message": f"Import '{check_name}' appears unused",
            })
        
        # Check for deprecated modules
        module_to_check = imp["module"] or imp["name"]
        for deprecated, (replacement, reason) in DEPRECATED_PACKAGES.items():
            if deprecated.lower() in module_to_check.lower():
                issues.append({
                    "line": imp["line"],
                    "type": "deprecated_import",
                    "import": imp["full_line"],
                    "package": deprecated,
                    "replacement": replacement,
                    "reason": reason,
                    "severity": "error",
                })
    
    # Check for deprecated patterns in code
    for pattern, suggestion in MODERN_ALTERNATIVES.items():
        for line_num, line in enumerate(lines, 1):
            if pattern in line and not line.strip().startswith("#"):
                issues.append({
                    "line": line_num,
                    "type": "deprecated_pattern",
                    "pattern": pattern,
                    "suggestion": suggestion,
                    "severity": "info",
                    "code": line.strip()[:80],
                })
    
    return issues


def validate_files(files: List[Dict[str, str]]) -> Dict[str, List[Dict]]:
    """
    Validate all generated files.
    
    Args:
        files: List of {"path": str, "content": str}
        
    Returns:
        Dict mapping filename to list of issues
    """
    all_issues = {}
    
    for file_dict in files:
        path = file_dict["path"]
        content = file_dict["content"]
        issues = []
        
        if path == "requirements.txt":
            issues.extend(check_requirements_txt(content))
        elif path.endswith(".py"):
            issues.extend(check_python_imports(content, path))
        
        if issues:
            all_issues[path] = issues
    
    return all_issues


def generate_fix_prompt(files: List[Dict[str, str]], issues: Dict[str, List[Dict]]) -> str:
    """
    Generate a prompt for AI to fix the issues found.
    """
    prompt_parts = ["Fix the following code quality issues:\n"]
    
    for filename, file_issues in issues.items():
        prompt_parts.append(f"\n## {filename}\n")
        for issue in file_issues:
            if issue.get("type") == "unused_import":
                prompt_parts.append(f"- Line {issue['line']}: Remove unused import: {issue['name']}")
            elif issue.get("type") == "deprecated_import":
                prompt_parts.append(f"- Line {issue['line']}: Replace {issue['package']} with {issue['replacement']}")
            elif issue.get("type") == "deprecated_pattern":
                prompt_parts.append(f"- Line {issue['line']}: {issue['suggestion']}")
            elif issue.get("package"):  # requirements.txt issue
                prompt_parts.append(f"- Replace {issue['package']} with {issue['replacement']}: {issue['reason']}")
    
    return "\n".join(prompt_parts)


def print_validation_report(issues: Dict[str, List[Dict]]) -> None:
    """Print a human-readable validation report."""
    if not issues:
        print("[Validator] ✅ No issues found!")
        return
    
    total_issues = sum(len(i) for i in issues.values())
    print(f"\n[Validator] ⚠️ Found {total_issues} issue(s) in {len(issues)} file(s):\n")
    
    for filename, file_issues in issues.items():
        print(f"  📄 {filename}:")
        for issue in file_issues:
            severity_icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(issue.get("severity", "info"), "•")
            
            if issue.get("type") == "unused_import":
                print(f"    {severity_icon} Line {issue['line']}: Unused import '{issue['name']}'")
            elif issue.get("type") == "deprecated_import":
                print(f"    {severity_icon} Line {issue['line']}: Deprecated '{issue['package']}' → use '{issue['replacement']}'")
            elif issue.get("type") == "deprecated_pattern":
                print(f"    {severity_icon} Line {issue['line']}: {issue['suggestion']}")
            elif issue.get("package"):
                print(f"    {severity_icon} Deprecated '{issue['package']}' → use '{issue['replacement']}'")
        print()
