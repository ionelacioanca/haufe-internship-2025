from flask import Flask, render_template, request, jsonify, redirect, url_for
import json
import pathlib
import subprocess
import os
import sys

app = Flask(__name__)

# --- Define paths ---
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
RULES_FILE = BASE_DIR / "rules" / "custom_rules.json"
PATCH_DIR = BASE_DIR / "patches"

# --- Ensure required dirs exist ---
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
PATCH_DIR.mkdir(parents=True, exist_ok=True)

# --- Keep track of last analyzed file ---
LAST_ANALYZED_FILE = None

# ---------------- HOME / REVIEW PAGE ----------------
@app.route("/")
def review():
    """Display the last AI code review report."""
    report_path = REPORTS_DIR / "review.md"
    review_md = report_path.read_text(encoding="utf-8") if report_path.exists() else "No review report found yet."
    return render_template("review.html", review_md=review_md)

# ---------------- ADD COMMENT TO LAST ANALYZED FILE ----------------
@app.route("/submit", methods=["POST"])
def submit_comment():
    """Adds developer comment directly to the last analyzed file."""
    global LAST_ANALYZED_FILE
    comment = request.form.get("comment", "").strip()

    if not comment:
        return "❌ Comment cannot be empty.", 400
    if not LAST_ANALYZED_FILE:
        return "⚠️ No file has been analyzed yet. Please run a code review first.", 400

    target_file = (BASE_DIR / LAST_ANALYZED_FILE).resolve()
    if not target_file.exists():
        return f"❌ Last analyzed file not found: {target_file}", 404

    try:
        with open(target_file, "a", encoding="utf-8") as f:
            f.write(f"\n\n# 💬 Developer comment:\n# {comment}\n")
        print(f"✅ Comment added to {target_file}")
        return redirect(url_for("review"))
    except Exception as e:
        return f"⚠️ Error writing comment: {e}", 500

# ---------------- ADD CUSTOM CODING RULE ----------------
@app.route("/add_rule", methods=["POST"])
def add_rule():
    try:
        new_rule = request.form.get("rule", "").strip()
        if not new_rule:
            return jsonify({"status": "error", "message": "Rule cannot be empty."}), 400

        RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        rules = {}

        if RULES_FILE.exists():
            try:
                rules = json.loads(RULES_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                rules = {}

        if "rules" not in rules:
            rules["rules"] = []

        rules["rules"].append(new_rule)
        RULES_FILE.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")

        return jsonify({"status": "success", "message": "✅ Rule added successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ---------------- RUN AI REVIEW FOR SPECIFIC FILE ----------------
@app.route("/analyze_file", methods=["POST"])
def analyze_file():
    global LAST_ANALYZED_FILE
    try:
        data = request.get_json()
        filepath = data.get("filepath", "").strip()

        if not filepath:
            return jsonify({"status": "⚠️ No file path provided."}), 400

        abs_path = (BASE_DIR / filepath).resolve()
        if not abs_path.exists():
            return jsonify({"status": f"❌ Invalid file path: {abs_path}"}), 400

        print(f"🔍 Running AI Code Review for {abs_path}...")

        LAST_ANALYZED_FILE = filepath  # <-- Save it globally for later comments

        cmd = f"python -m orchestrator.main --file={filepath}"
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )

        output = result.stdout + "\n" + result.stderr
        print("=== REVIEW OUTPUT ===\n", output)

        report_path = REPORTS_DIR / "review.md"
        if not report_path.exists():
            return jsonify({"status": "❌ Code Review failed — no report generated.", "output": output})

        review_md = report_path.read_text(encoding="utf-8")

        return jsonify({
            "status": f"✅ Code Review complete for {filepath}",
            "output": output,
            "report": review_md
        })

    except Exception as e:
        print(f"❌ Error during review: {e}")
        return jsonify({"status": f"❌ Exception: {e}"}), 500

# ---------------- GENERATE AUTO-FIX PATCH (use last analyzed file) ----------------
@app.route("/generate_autofix", methods=["POST"])
def generate_autofix():
    global LAST_ANALYZED_FILE
    try:
        if not LAST_ANALYZED_FILE:
            return jsonify({"status": "⚠️ No file analyzed yet. Please run a review first.", "patch": ""})

        target_file = LAST_ANALYZED_FILE
        print(f"🔧 Generating auto-fix for last analyzed file: {target_file}")

        result = subprocess.run(
            [sys.executable, "-m", "orchestrator.main", f"--file={target_file}"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )

        print("=== PATCH GENERATION OUTPUT ===")
        print(result.stdout + result.stderr)

        patch_files = sorted(PATCH_DIR.glob("*.diff"), key=os.path.getmtime)
        latest_patch = patch_files[-1] if patch_files else None

        if latest_patch and latest_patch.exists():
            patch_content = latest_patch.read_text(encoding="utf-8")
            return jsonify({
                "status": f"✅ Patch generated for {target_file}",
                "patch": patch_content,
                "file": target_file
            })
        else:
            return jsonify({"status": "⚠️ No patch generated.", "patch": "", "file": target_file})

    except Exception as e:
        return jsonify({"status": "❌ Error generating patch", "patch": str(e)})


# ---------------- GIT COMMIT (fixed for Windows + correct cwd) ----------------
@app.route("/commit", methods=["POST"])
def run_commit():
    try:
        repo_path = BASE_DIR

        print(f"💾 Running Git commit in {repo_path}...")

        result_add = subprocess.run(
            ["git", "add", "."],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )

        result_commit = subprocess.run(
            ["git", "commit", "-m", "Frontend commit"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )

        output = f"=== git add ===\n{result_add.stdout}\n{result_add.stderr}\n\n=== git commit ===\n{result_commit.stdout}\n{result_commit.stderr}"

        if "nothing to commit" in result_commit.stdout:
            status = "⚠️ No changes to commit."
        elif result_commit.returncode == 0:
            status = "✅ Commit executed successfully!"
        else:
            status = "❌ Commit failed."

        print(output)
        return jsonify({"status": status, "output": output})

    except Exception as e:
        return jsonify({"status": "❌ Error running commit", "output": str(e)})

# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(debug=True)
