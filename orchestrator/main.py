import subprocess
import json
import pathlib
import os
import webbrowser
import requests
import time

ai_usage_log = []

# ---------- Helper functions ----------
def track_ai_usage(action_name, start_time):
    """Track and log time spent on each AI-related action."""
    import time
    duration = time.time() - start_time
    ai_usage_log.append((action_name, duration))
    print(f"Tracked AI usage for {action_name}: {duration:.2f}s")

def load_custom_rules():
    rules_path = pathlib.Path("rules/custom_rules.json")
    if rules_path.exists():
        with open(rules_path, "r", encoding="utf-8") as file:
            return json.load(file)
    return {}

def timed_section(label, func, *args, **kwargs):
    """Measure execution time of any given function."""
    print(f"Starting: {label} ...")
    start = time.time()
    result = func(*args, **kwargs)
    duration = time.time() - start
    print(f"Finished {label} in {duration:.2f} seconds.")
    return result, duration

def run_command(cmd, cwd=None):
    """Run a shell command and return stdout as text."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.stdout.strip()

def get_changed_files():
    """Return a list of changed Python files since last commit."""
    try:
        result = subprocess.run(["git", "diff", "--name-only", "HEAD"], capture_output=True, text=True)
        files = [f.strip() for f in result.stdout.splitlines() if f.endswith(".py")]
        return files
    except Exception as e:
        print(f"Error getting changed files: {e}")
        return []


def run_ruff(repo_path):
    """Run Ruff and return parsed JSON findings."""
    print("Running Ruff...")
    output = run_command(["ruff", "check", "--output-format", "json", "."], cwd=repo_path)
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return []

def run_bandit(repo_path):
    """Run Bandit and return parsed JSON findings."""
    print("Running Bandit...")
    output = run_command(["bandit", "-r", ".", "-f", "json"], cwd=repo_path)
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {}
    
def check_architecture_structure():
    """Simple architectural check for folder organization."""
    print("Performing architecture structure check...")
    required_dirs = ["orchestrator", "sample", "reports"]
    missing = [d for d in required_dirs if not pathlib.Path(d).exists()]
    if missing:
        return [f"Missing expected module directories: {', '.join(missing)}"]
    return ["Project structure follows modular architecture."]
    
custom_rules = load_custom_rules()
if custom_rules:
    print("Applying custom coding rules...")

def analyze_with_llm(findings, model="qwen2.5-coder:0.5b"):
    start_time = time.time()
    """Send a summarized report to the local LLM (Ollama)."""
    print("Analyzing findings with local LLM...")

    # Build a simple prompt
    if not findings:
        issues_text = "No issues were found, but please review the code quality overall."
    else:
        issues_text = "\n".join(
            f"- {f.get('message', f)} (in {f.get('filename', 'unknown file')})"
            for f in findings
        )

    custom_rules_text = json.dumps(custom_rules, indent=2)
    prompt = f"""Perform a code review according to standard guidelines (PEP8, Google Style)
and the following project-specific rules:
{custom_rules_text}

Here are some code issues detected by static analyzers:
{issues_text}

Provide:
1. A short summary of overall code quality.
2. The 3 most important improvements.
3. Concrete code examples where possible.
"""

    # New API format for Ollama (v0.3+)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an expert software engineer performing a code review."},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=180)

    if response.status_code != 200:
        print(f"Ollama returned error {response.status_code}: {response.text}")
        return "Error: LLM could not generate a response."

    data = response.json()
    track_ai_usage("analyze_with_llm", start_time)
    return data.get("message", {}).get("content", "").strip()

def generate_auto_fix(findings, model="qwen2.5-coder:0.5b"):
    start_time = time.time()
    """Ask the local LLM to propose automatic fixes for the detected issues."""
    if not findings:
        return None

    print("Generating automatic fixes with LLM...")

    issues_text = "\n".join(
        f"- {f.get('message', f)} (in {f.get('filename', 'unknown file')})"
        for f in findings
    )

    prompt = f"""You are an expert software engineer.
Below are code issues detected in a project:

{issues_text}

Please generate a unified diff (git patch format) that shows how to fix
the most critical issues. The diff must start with lines like:
--- old_filename.py
+++ new_filename.py
@@ line,line @@
and contain valid, minimal changes.
Do not explain the changes outside of the diff.
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a senior developer creating precise code fixes."},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    try:
        response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=180)
        if response.status_code != 200:
            print(f"Ollama returned error {response.status_code}: {response.text}")
            return None

        data = response.json()
        patch_text = data.get("message", {}).get("content", "").strip()

        # Save patch
        patch_path = pathlib.Path("patches") / f"auto_fix_{int(time.time())}.diff"
        patch_path.write_text(patch_text, encoding="utf-8")

        print(f"Auto-fix patch saved to: {patch_path}")
        return patch_path

    except Exception as e:
        print(f"Error while generating auto-fix: {e}")
        track_ai_usage("generate_auto_fix", start_time)
        return None
    
def estimate_effort(findings, model="qwen2.5-coder:0.5b"):
    start_time = time.time()
    """Ask the local LLM to estimate developer effort needed for fixes."""
    if not findings:
        return "No issues found, no effort required."

    print("Estimating development effort with LLM...")

    issues_text = "\n".join(
        f"- {f.get('message', f)} (in {f.get('filename', 'unknown file')})"
        for f in findings
    )

    prompt = f"""You are an experienced software project manager.
Below are code issues found in a code review:

{issues_text}

Estimate the total effort needed to address all issues.
Provide your answer in the format:
"Effort estimation: <Low/Medium/High> (~X hours of developer work)"
Briefly explain why.
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an expert project manager."},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    try:
        response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=180)
        if response.status_code != 200:
            print(f"Ollama returned error {response.status_code}: {response.text}")
            return "Effort estimation unavailable (error from LLM)."

        data = response.json()
        effort_text = data.get("message", {}).get("content", "").strip()
        print("Effort estimation complete.")
        return effort_text

    except Exception as e:
        print(f"Error while estimating effort: {e}")
        track_ai_usage("estimate_effort", start_time)
        return "Error while estimating effort."
    
def add_comment_section(findings):
    """Append a developer comment/reply section to the markdown report."""
    if not findings:
        return

    print("Adding developer comment section to report...")

    section = "\n\n---\n### Developer Responses\n"
    for i, f in enumerate(findings, start=1):
        filename = f.get("filename", "unknown file")
        line = f.get("line", "?")
        message = f.get("message", "").strip()
        section += (
            f"{i}. **{filename}, line {line}** – {message}\n"
            f"   - [ ] Fixed\n"
            f"   - [ ] Not applicable\n"
            f"   - **Comment:** _Write your reply here..._\n\n"
        )

    with open("reports/review.md", "a", encoding="utf-8") as report_file:
        report_file.write(section)

    print(" Developer comment section added.")

def document_findings(findings, model="qwen2.5-coder:0.5b"):
    start_time = time.time()
    """Generate clear documentation for each finding in the code review."""
    if not findings:
        print("No findings to document.")
        return

    print("Generating documentation for findings...")

    # Limit to a reasonable number for faster processing
    sample_findings = findings[:10]
    findings_text = "\n".join(
        f"- {f.get('message', f)} (File: {f.get('filename', 'unknown')}, line {f.get('line', '?')})"
        for f in sample_findings
    )

    prompt = f"""You are a technical writer specialized in software documentation.
Below is a list of code issues found during an AI-assisted review.

For each issue, write:
1. A short explanation of what the problem means (plain language).
2. Why it can cause bugs or security issues.
3. A short code example showing how to fix it properly.

List them clearly in markdown format.

Issues:
{findings_text}
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a clear and concise documentation assistant."},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    try:
        response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=180)
        if response.status_code != 200:
            print(f"Ollama returned error {response.status_code}: {response.text}")
            return

        data = response.json()
        doc_text = data.get("message", {}).get("content", "").strip()

        with open("reports/review.md", "a", encoding="utf-8") as report_file:
            report_file.write("\n\n---\n")
            report_file.write("### Documentation for Findings\n")
            report_file.write(doc_text)

        print("Documentation for findings added to report.")

    except Exception as e:
        print(f"Error while documenting findings: {e}")
    track_ai_usage("document_findings", start_time)

def suggest_doc_updates(findings, model="qwen2.5-coder:0.5b"):
    start_time = time.time()
    """Ask the local LLM to suggest documentation updates based on code changes."""
    if not findings:
        return

    print("Suggesting documentation updates...")
    issues_text = "\n".join(
        f"- {f.get('message', f)} (in {f.get('filename', 'unknown file')})"
        for f in findings[:10]
    )

    prompt = f"""You are a software documentation assistant.
Based on the following code issues:

{issues_text}

Suggest updates for the project's documentation, such as:
- functions or modules that need improved docstrings
- parts of the README that should mention new security or configuration notes
- high-level descriptions to keep docs in sync with the latest changes

Output in clear markdown format."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a technical writer improving documentation clarity."},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    try:
        response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=180)
        if response.status_code != 200:
            print(f"Ollama returned error {response.status_code}: {response.text}")
            return

        data = response.json()
        doc_update_text = data.get("message", {}).get("content", "").strip()

        with open("reports/review.md", "a", encoding="utf-8") as report_file:
            report_file.write("\n\n---\n")
            report_file.write("### 🪶 Suggested Documentation Updates\n")
            report_file.write(doc_update_text)

        print("Suggested documentation updates added.")
    except Exception as e:
        print(f"Error suggesting documentation updates: {e}")
    track_ai_usage("suggest_doc_updates", start_time)


def save_report(report_text, output_path):
    """Save the AI-generated report to a Markdown file."""
    reports_dir = pathlib.Path(output_path)
    reports_dir.mkdir(parents=True, exist_ok=True)
    file_path = reports_dir / "review.md"
    file_path.write_text(report_text, encoding="utf-8")
    print(f"Report saved to: {file_path.resolve()}")


# ---------- Main orchestration ----------

def main(mode="full", file_target=None):
    print("Starting AI Code Review Assistant...")

    repo_path = pathlib.Path("sample").resolve()
    model = "qwen2.5-coder:0.5b"
    performance_stats = []

    # --- STEP 1: Decide what files to analyze ---
    if mode in ("file", "file_specific") and file_target:
        if not os.path.exists(file_target):
            print(f"File not found: {file_target}")
            return
        changed_files = [file_target]
        print(f"Running analysis for single file: {file_target}")

    elif mode == "incremental":
        changed_files = get_changed_files()
        if changed_files:
            print(f"Detected changed files: {changed_files}")
        else:
            print("No changed files detected. Skipping analysis.")
            return

    else:
        changed_files = [str(p) for p in repo_path.rglob("*.py")]
        print(f"Running full analysis on {len(changed_files)} files...")


    # --- STEP 2: Run analyzers only on selected files ---
    all_ruff_results = []
    all_bandit_results = {"results": []}

    for file_path in changed_files:
        file_dir = str(pathlib.Path(file_path).parent)
        print(f"Analyzing {file_path} ...")
        ruff_output, ruff_time = timed_section("Ruff Analysis", run_ruff, file_dir)
        performance_stats.append(("Ruff", ruff_time))
        all_ruff_results += ruff_output
        bandit_output, bandit_time = timed_section("Bandit Analysis", run_bandit, file_dir)
        performance_stats.append(("Bandit", bandit_time))
        if "results" in bandit_output:
            all_bandit_results["results"].extend(bandit_output["results"])

    # --- STEP 3: Gather all findings ---
    findings = []
    for item in all_ruff_results:
        for msg in item.get("messages", []):
            findings.append({
                "tool": "ruff",
                "filename": item.get("filename"),
                "message": msg.get("message"),
                "line": msg.get("location", {}).get("row"),
            })
    for issue in all_bandit_results.get("results", []):
        findings.append({
            "tool": "bandit",
            "filename": issue.get("filename"),
            "message": issue.get("issue_text"),
            "line": issue.get("line_number"),
        })

    architecture_notes = check_architecture_structure()
    for note in architecture_notes:
        findings.append({
            "tool": "architecture",
            "filename": "project",
            "message": note,
            "line": 0
        })


    print(f"Collected {len(findings)} issues total.")

    # --- STEP 4: Send findings to LLM ---
    ai_review, ai_time = timed_section("AI Analysis", analyze_with_llm, findings, model=model)
    performance_stats.append(("AI Review", ai_time))


    # --- STEP 5: Save the AI-generated report ---
    save_report(ai_review, "reports")

    # --- STEP 6: Generate automatic patch suggestion ---
    _, fix_time = timed_section("Generate Auto Fix", generate_auto_fix, findings, model=model)
    performance_stats.append(("Auto Fix", fix_time))


    # --- STEP 7: Estimate developer effort ---
    effort_text, effort_time = timed_section("Effort Estimation", estimate_effort, findings, model=model)
    performance_stats.append(("Effort Estimation", effort_time))

    with open("reports/review.md", "a", encoding="utf-8") as report_file:
        report_file.write("\n\n---\n")
        report_file.write("### Effort Estimation\n")
        report_file.write(effort_text)

    # --- STEP 8: Add developer comment section ---
    add_comment_section(findings)

    # --- STEP 9: Generate documentation for findings ---
    _, doc_time = timed_section("Document Findings", document_findings, findings, model=model)
    performance_stats.append(("Document Findings", doc_time))

    with open("reports/review.md", "a", encoding="utf-8") as report_file:
        report_file.write("\n\n---\n")
        report_file.write("### Coding Guideline Awareness\n")
        report_file.write("This review follows **PEP8** and **Google Python Style Guide** recommendations as enforced by Ruff.\n")

    # --- STEP 10: Suggest documentation updates ---
    _, suggest_time = timed_section("Suggest Documentation Updates", suggest_doc_updates, findings, model=model)
    performance_stats.append(("Doc Updates", suggest_time))

    # --- STEP: Write performance summary to report ---
    total_time = sum(t for _, t in performance_stats)
    with open("reports/review.md", "a", encoding="utf-8") as report_file:
        report_file.write("\n\n---\n")
        report_file.write("### Performance Summary\n")
        for name, t in performance_stats:
            report_file.write(f"- {name}: {t:.2f} seconds\n")
        report_file.write(f"\n**Total execution time:** {total_time:.2f} seconds\n")

        # --- STEP: Write AI Cost Management summary ---
    if ai_usage_log:
        total_ai_time = sum(t for _, t in ai_usage_log)
        estimated_cost = total_ai_time * 0.0001  # simulated cost per second of AI runtime
        with open("reports/review.md", "a", encoding="utf-8") as report_file:
            report_file.write("\n\n---\n")
            report_file.write("### AI Cost Management\n")
            for name, t in ai_usage_log:
                report_file.write(f"- {name}: {t:.2f} seconds\n")
            report_file.write(f"\n**Total AI time:** {total_ai_time:.2f} seconds\n")
            report_file.write(f"**Simulated cost:** ${estimated_cost:.4f}\n")

        print(f"Total AI processing time: {total_ai_time:.2f}s (simulated cost: ${estimated_cost:.4f})")

    print("Code review complete!")

     # --- STEP: Launch local frontend UI for developer comments ---
'''
    import subprocess
    import time
    import webbrowser

    try:
        print("Launching local review interface...")
        subprocess.Popen(
            ["python", "frontend/app.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(2)  # give Flask 2 seconds to start
        webbrowser.open("http://127.0.0.1:5000")
        print("Review interface opened in browser.")
    except Exception as e:
        print(f"Could not launch frontend automatically: {e}") '''

if __name__ == "__main__":
    import sys
    import os

    mode = "full"
    file_target = None

    for arg in sys.argv[1:]:
        if arg == "--mode=incremental":
            mode = "incremental"
        elif arg.startswith("--file="):
            mode = "file"
            file_target = arg.split("=", 1)[1]

    print(f"Running orchestrator in mode: {mode}")
    if file_target:
        print(f"Target file: {file_target}")

    main(mode, file_target)
