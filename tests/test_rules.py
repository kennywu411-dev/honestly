from honestly import rules as R

def test_python_heredoc_edit_is_edit():
    cmd = "cd \"/x/工程文件\" && python3 -I - <<'EOF'\np='js/engine.js'; s=open(p).read()\ns=s.replace('a','b')\nopen(p,'w').write(s)\nEOF"
    assert R.bash_is_edit(cmd)
    assert not R.bash_verifies(cmd, {"test", "run"})          # an edit never verifies itself

def test_python_heredoc_doc_edit_is_not_edit():
    cmd = "python3 - <<'EOF'\np='docs/HANDOFF.md'; s=open(p).read()\nopen(p,'w').write(s)\nEOF"
    assert not R.bash_is_edit(cmd)

def test_cat_append_test_file_is_edit_and_not_verification():
    cmd = "cat >> tests/test_llm.py <<'EOF'\n\ndef test_x():\n    assert pytest\nEOF"
    assert R.bash_is_edit(cmd)
    assert not R.bash_verifies(cmd, {"test"})

def test_cat_append_log_is_not_edit():
    cmd = "cd ~/p; cat >> docs/迭代日志.md <<'EOF'\n## sed -i something > x.py\nEOF"
    assert not R.bash_is_edit(cmd)

def test_sed_readme_not_edit():
    assert not R.bash_is_edit("sed -i '' 's/a/b/' README.md && sed -i '' 's/c/d/' docs/x.md")

def test_sed_code_is_edit():
    assert R.bash_is_edit("sed -i '' 's/a/b/' src/app.py")

def test_commit_email_not_edit():
    assert not R.bash_is_edit('git add -A && git commit -q -m "docs: x\n\nCo-Authored-By: C <c@example.com>"')

def test_comparison_not_redirect():
    assert not R.bash_is_edit("python3 -c \"import sys; print(1 if 2>=1 else 0)\"")

def test_versioned_hyperframes_check_verifies():
    assert R.bash_verifies("cd x; npx --yes hyperframes@0.8.186 check 2>&1 | tail -8", {"build", "test"})

def test_edit_then_run_counts_after_edit():
    cmd = "sed -i '' 's/a/b/' A.py && blender -b -P A.py"
    assert R.bash_is_edit(cmd)
    assert R.bash_verifies(cmd, {"render"}, after_edit_only=True)

def test_pytest_piped_detected_as_pipe():
    segs = R.verifying_segments("uv run pytest -q 2>&1 | tail -8", {"test"})
    assert segs and R.PIPE_SWALLOW.search(segs[0].text)

def test_claims_exclude_plans_and_quotes():
    assert not R.find_claims("接下来我会跑测试，应该全部通过。")
    assert not R.find_claims('审查机器人标记"所有问题已修复"。')
    assert R.find_claims("33 个测试全部通过。")[0].category == "tests_pass"

def test_semicolon_inside_sed_quotes_not_split():
    cmd = "cd /x && sed -i '' 's/a;b/c;d/g; s/e/f/' docs/台账.md"
    assert not R.bash_is_edit(cmd)
    assert R.bash_is_edit("sed -i '' 's/a;b/c;d/g; s/e/f/' src/app.py")

def test_state_json_is_doc():
    cmd = "python3 - <<'EOF'\nimport json; p='.agent/state.json'; s=json.load(open(p)); json.dump(s,open(p,'w'))\nEOF"
    assert not R.bash_is_edit(cmd)

def test_argv_scratch_target_not_edit():
    cmd = "F=/private/tmp/claude-501/x/scratchpad/page.html; python3 - \"$F\" <<'EOF'\nimport sys\np=sys.argv[1]; s=open(p).read()\nopen(p,'w').write(s.replace('a','b'))\nEOF"
    assert not R.bash_is_edit(cmd)

def test_multiline_commit_message_is_one_segment():
    cmd = 'git add -A && git commit -q -m "fix: x\n\n- ran tests/test_a.py\nCo-Authored-By: C <c@example.com>" 2>&1 | tail -1 && uv run pytest -q | tail -1'
    segs = R.segments(cmd)
    assert any(sg.text.startswith("git commit") for sg in segs)
    assert not any("Co-Authored" in sg.text and not sg.text.startswith("git commit") for sg in segs)
    assert R.verifying_segments(cmd, {"test"})[-1].text.startswith("uv run pytest")

def test_doc_writing_python_heredoc_is_not_verification():
    cmd = "python3 - <<'EOF'\np='CLAUDE.md'; s=open(p).read()\nopen(p,'w').write(s)\nEOF"
    assert not R.bash_verifies(cmd, {"run", "test"})

def test_program_output_redirect_is_not_edit():
    assert not R.bash_is_edit("honestly audit --json x.jsonl 2>/dev/null > gate/final_summary.json")
    assert not R.bash_is_edit("uv run pytest -q > runs/test.log 2>&1")
    assert R.bash_is_edit("echo 'x=1' > src/config.py")
    assert R.bash_is_edit("printf 'a\\n' > src/app.js")

def test_git_bookkeeping_is_not_an_edit():
    assert not R.bash_is_edit("git reset -q --soft HEAD~1 && git restore --staged .github && git add -A")
    assert R.bash_is_edit("git checkout -- src/app.py")
    assert R.bash_is_edit("git reset --hard HEAD~1")


def test_fixed_as_adjective_is_not_a_claim():
    assert not R.find_claims("Pyrolysis behavior of vitrinite from Pingshuo coal by TG-MS and in a fixed bed reactor.")
    assert not R.find_claims("Pyrolysis of coal in a fixed-bed reactor[J].")
    assert not R.find_claims("Use a fixed-point iteration with a fixed width buffer.")
    assert not R.find_claims("Smith J, et al. Catalyst design. Journal of Catalysis, 2021, vol. 3: 12-20.")

def test_fixed_as_completion_is_a_claim():
    for sent in ["Fixed the off-by-one in the parser.", "The crash is now fixed.", "Bug fixed, tests pass.",
                 "fixed in commit abc123", "Fixed.", "I fixed both issues", "问题已修复。"]:
        hits = R.find_claims(sent)
        assert hits and hits[0].category in ("fixed", "tests_pass"), sent


def test_fix_followed_by_pending_check_is_not_a_final_claim():
    assert not R.find_claims("It's fixed now, and I'm re-rendering to check the houses.")
