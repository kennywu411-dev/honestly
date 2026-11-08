"""shell.py reads a command the way a shell does. Each case here was checked against bash; nothing in the reader runs anything."""
import pytest

from honestly import shell


def commands(src):
    """The command names that would be read, in order, with whether each would run."""
    return [(u.text.split("\n", 1)[0], u.guard) for u in shell.units(src)]


def texts(src, level=None):
    return [u.text for u in shell.units(src) if level is None or u.level == level]


@pytest.mark.parametrize("src,want", [
    ("a && b || c ; d & e", ["a", "b", "c", "d", "e"]),
    ("a&&b||c;d&e", ["a", "b", "c", "d", "e"]),
    ("a\nb\n\nc", ["a", "b", "c"]),
    ("a | b |& c", ["a | b |& c"]),
    ("a |\n b", ["a |\n b"]),
    ("a \\\n  b", ["a \\\n  b"]),
    ("echo 'a; b' \"c; d\" e\\;f; g", ["echo 'a; b' \"c; d\" e\\;f", "g"]),
    ("echo 'it'\\''s'; b", ["echo 'it'\\''s'", "b"]),
    ("echo it\\'s; b", ["echo it\\'s", "b"]),
    ("echo 'a\\'; b", ["echo 'a\\'", "b"]),
    ('echo "a\\\\"; b', ['echo "a\\\\"', "b"]),
    ("echo $((1<<3)); b", ["echo $((1<<3))", "b"]),
    ("x=$((1 << 4)); b", ["x=$((1 << 4))", "b"]),
    ("read x <<< abc; b", ["read x <<< abc", "b"]),
    ("# use <<EOF\nb", ["b"]),
    ("a # it's a comment\nb", ["a", "b"]),
    ("echo a#b; c", ["echo a#b", "c"]),
    ("echo $#; c", ["echo $#", "c"]),
    ("echo ${#x}; c", ["echo ${#x}", "c"]),
    ("(a; b)", ["a", "b"]),
    ("{ a; b; }", ["a", "b"]),
    ("if a; then b; elif c; then d; else e; fi", ["a", "b", "c", "d", "e"]),
    ("if a\nthen\n  b\nfi", ["a", "b"]),
    ("for i in 1 2; do a; b; done", ["a", "b"]),
    ("for i in 1 2\ndo\n  a\ndone", ["a"]),
    ("while a; do b; done < list", ["a", "b"]),
    ("until a; do b; done", ["a", "b"]),
    ("case x in x) a;; y|z) b;; esac", ["a", "b"]),
    ("f() { a; }; f", ["f", "a"]),
    ("function f { a; }; f", ["f", "a"]),
    ("! a", ["a"]),
    ("A=1 B=2 a", ["A=1 B=2 a"]),
    ("[[ a > b ]] && c", ["c"]),
    ("(( x > 5 )) && c", ["c"]),
    ("", []),
    ("   \n  ", []),
])
def test_splitting(src, want):
    assert texts(src, 0) == want


@pytest.mark.parametrize("src,term,body", [
    ("cat <<EOF\nx\ny\nEOF", "EOF", "x\ny"),
    ("cat <<'EOF'\n$(a | b)\nEOF", "EOF", "$(a | b)"),
    ('cat <<"E O"\nx\nE O', "E O", "x"),
    ("cat <<\\EOF\nx\nEOF", "EOF", "x"),
    ("cat <<-EOF\n\tx\n\tEOF", "EOF", "\tx"),
    ("cat <<'END-OF'\nx\nEND-OF", "END-OF", "x"),
    ("cat <<EOF\nno end", "EOF", "no end"),
])
def test_heredocs(src, term, body):
    h = shell.parse(src).pipelines[0].commands[0].heredocs[0]
    assert (h.term, h.body) == (term, body)


def test_a_command_after_a_heredoc_head_is_a_command():
    assert texts("cat <<EOF && b\nx\nEOF", 0) == ["cat <<EOF\nx\nEOF", "b"]
    assert texts("cat <<EOF | b\nx\nEOF\nc", 0) == ["cat <<EOF | b\nx\nEOF", "c"]
    assert texts("cat <<A <<B\na\nA\nb\nB\nc", 0)[-1] == "c"


def test_the_body_of_a_quoted_heredoc_is_data():
    assert [u.text for u in shell.units("cat <<'EOF'\n$(a | b)\nEOF")] == ["cat <<'EOF'\n$(a | b)\nEOF"]
    assert "a | b" in [u.text for u in shell.units("cat <<EOF\n$(a | b)\nEOF")]


@pytest.mark.parametrize("src,inner", [
    ("x=$(a | b)", "a | b"), ('echo "$(a | b)"', "a | b"), ("x=`a | b`", "a | b"), ("cat <(a | b)", "a | b"), ("bash -c 'a | b'", "a | b"), ('sh -c "a | b"', "a | b"), ("bash -ec 'a | b'", "a | b"),
    ("bash -euo pipefail -c 'a | b'", "a | b"), ("eval 'a | b'", "a | b"), ("bash <<'EOF'\na | b\nEOF", "a | b"), ("echo 'a | b' | sh", "a | b"), ("cat <<'EOF' | bash\na | b\nEOF", "a | b"), ("sh <<< 'a | b'", "a | b"),
    ("xargs sh -c 'a | b'", "a | b"), ("timeout 5 bash -c 'a | b'", "a | b"), ("bash -c \"bash -c 'a | b'\"", "a | b"),
])
def test_text_that_runs_is_read(src, inner):
    assert inner in texts(src)


@pytest.mark.parametrize("src", ["echo '$(a | b)'", 'echo "\\$(a | b)"', "# $(a | b)", "echo 'a | b'", "cat <<'EOF'\na | b\nEOF", "git commit -m 'a | b'", "printf '%s' 'a | b'", "echo bash -c 'a | b'"])
def test_text_that_does_not_run_is_not_read(src):
    assert "a | b" not in texts(src)


@pytest.mark.parametrize("src,guard", [
    ("false && a", "no"), ("true || a", "no"), ("if false; then a; fi", "no"), ("if true; then a; fi", "yes"), ("while false; do a; done", "no"), ("for f in; do a; done", "no"), ("for f in x; do a; done", "yes"),
    ("case a in b) a;; esac", "no"), ("case a in a) a;; esac", "yes"), ("exit 0; a", "no"), ("exit 1\na", "no"), ("(exit 0); a", "yes"), ("true && a", "yes"), ("false || a", "maybe"), ("[ -f x ] && a", "maybe"), ("test -f x && a", "maybe"),
    ("grep -q x y && a", "maybe"), ("command -v a && a", "maybe"), ("if [ -f x ]; then a; fi", "maybe"), ("while read l; do a; done", "maybe"), ("cd x && a", "yes"), ("pip install x && a", "yes"), ("for x; do a; done", "maybe"),
])
def test_will_it_run(src, guard):
    assert [u.guard for u in shell.units(src) if u.text == "a"] == [guard]


def test_a_function_runs_when_called():
    assert "a" not in texts("t() { a; }")
    assert "a" in texts("t() { a; }; t")
    assert "a" in texts("function t { a; }\nt")


@pytest.mark.parametrize("src,masked", [
    ("a", False), ("a || true", True), ("a; true", True), ("a; echo done", True), ("a; exit 0", True), ("a || echo ok", True), ("a &", True), ("a || :", True), ("a; b", True),
    ("a && echo ok", False), ("a; echo $?", False), ("a; rc=$?", False), ("a; exit $?", False), ("a || exit 1", False), ("a || echo FAILED", False), ("a || { echo x; exit 1; }", False), ("set -e; a; b", False), ("a; echo ${PIPESTATUS[0]}", False),
])
def test_is_the_exit_status_lost(src, masked):
    assert [u.masked for u in shell.units(src) if u.text == "a"] == [masked]


@pytest.mark.parametrize("src,on", [
    ("set -o pipefail; a | b", True), ("set -euo pipefail\na | b", True), ("set -oe pipefail; a | b", True), ("set -e -o pipefail; a | b", True), ("set -o errexit -o pipefail; a | b", True), ("set -o pipefail -e; a | b", True),
    ("shopt -so pipefail; a | b", True), ("shopt -s -o pipefail; a | b", True), ("shopt -o -s pipefail; a | b", True), ("setopt pipefail; a | b", True), ("setopt PIPE_FAIL; a | b", True), ("bash -o pipefail -c 'a | b'", True), ("bash -euo pipefail -c 'a | b'", True),
    ("bash -euo pipefail <<'EOF'\na | b\nEOF", True), ("(set -o pipefail; a | b)", True), ("set -o pipefail; x=$(a | b)", True), ("set -o pipefail; (a | b)", True),
    ("(set -o pipefail); a | b", False), ("bash -c 'set -o pipefail'; a | b", False), ("echo set -o pipefail; a | b", False), ("if false; then set -o pipefail; fi; a | b", False), ("set -o pipefail; bash -c 'a | b'", False), ("a | b; set -o pipefail", False),
    ("set -o pipefail; set +o pipefail; a | b", False), ("set +o pipefail; a | b", False), ("reset -o pipefail; a | b", False), ("git commit -m 'set -o pipefail'; a | b", False), ("if x; then set -o pipefail; fi; a | b", False),
])
def test_is_pipefail_on(src, on):
    assert [u.pipefail for u in shell.units(src) if u.text == "a | b"] == [on]


@pytest.mark.parametrize("words,want", [
    (["pytest", "-q"], ["pytest", "-q"]), (["time", "-p", "pytest"], ["pytest"]), (["timeout", "-k", "5", "60", "pytest"], ["pytest"]), (["env", "-i", "A=1", "pytest"], ["pytest"]), (["nice", "-n", "5", "pytest"], ["pytest"]),
    (["sudo", "-u", "x", "pytest"], ["pytest"]), (["command", "pytest"], ["pytest"]), (["command", "-v", "pytest"], ["command", "-v", "pytest"]), (["uv", "run", "--frozen", "--with", "x", "pytest"], ["pytest"]), (["poetry", "run", "pytest"], ["pytest"]),
    (["npx", "--yes", "jest"], ["jest"]), (["bundle", "exec", "rspec"], ["rspec"]), (["pnpm", "exec", "vitest"], ["vitest"]), (["docker", "run", "-h", "box", "-e", "A=1", "img", "pytest"], ["pytest"]), (["docker", "compose", "exec", "-T", "web", "pytest"], ["pytest"]),
    (["docker-compose", "run", "--rm", "web", "pytest"], ["pytest"]), (["kubectl", "exec", "p", "--", "pytest"], ["pytest"]), (["nix", "develop", "-c", "pytest"], ["pytest"]), (["xargs", "-n", "1", "pytest"], ["pytest"]), (["xargs", "-I{}", "pytest", "{}"], ["pytest", "{}"]),
    (["find", ".", "-name", "x", "-exec", "pytest", "{}", "+"], ["pytest", "{}"]), (["coverage", "run", "-m", "pytest"], ["pytest"]), (["cargo", "+nightly", "test"], ["cargo", "test"]), (["$x", "=", "pytest"], ["pytest"]), (["/usr/bin/env", "pytest"], ["pytest"]),
    (["stdbuf", "-oL", "head", "-3"], ["head", "-3"]), (["xvfb-run", "-a", "pytest"], ["pytest"]), (["hatch", "run", "test"], ["hatch", "run", "test"]), (["hatch", "run", "python", "a.py"], ["python", "a.py"]), (["ssh", "-p", "22", "box", "pytest"], ["pytest"]),
])
def test_the_command_behind_the_wrappers(words, want):
    assert shell.unwrap(words) == want


def test_redirections():
    c = shell.parse("a > f 2>&1 >> g &> h 3> i < j >&2").pipelines[0].commands[0]
    assert [(r.fd, r.op, r.target) for r in c.redirects] == [("", ">", "f"), ("2", ">&", "1"), ("", ">>", "g"), ("", "&>", "h"), ("3", ">", "i"), ("", "<", "j"), ("", ">&", "2")]
    assert shell.stdout_dropped(shell.parse("a > /dev/null").pipelines[0].commands[0])
    assert shell.stdout_dropped(shell.parse("a 2>&1 >/dev/null").pipelines[0].commands[0])
    assert shell.stdout_dropped(shell.parse("a &> /dev/null").pipelines[0].commands[0])
    assert shell.stdout_dropped(shell.parse("a *> $null").pipelines[0].commands[0])
    assert not shell.stdout_dropped(shell.parse("a 2>/dev/null").pipelines[0].commands[0])
    assert not shell.stdout_dropped(shell.parse("a > log").pipelines[0].commands[0])


@pytest.mark.parametrize("src,want", [
    ("cd /a/b && c", "/a/b"), ("cd /a; cd b; c", "/a/b"), ("cd -P /a; c", "/a"), ("cd -- /a; c", "/a"), ("cd /a/b\\ c; c", "/a/b c"), ("cd '/a b'; c", "/a b"), ("P=/x; cd $P; c", "/x"), ("cd - ; c", None), ("cd $(pwd); c", None), ("(cd /a); c", ""), ("cd $HOME/p; c", "~/p"),
    ("if x; then cd /a; fi; c", None), ("for d in a b; do cd $d; c; done", None),
])
def test_where_a_command_runs(src, want):
    assert [u.cwd for u in shell.units(src) if u.text == "c"] == [want]


def test_it_reads_powershell_without_harm():
    assert texts("Get-Content a | Set-Content b; Write-Output c", 0) == ["Get-Content a | Set-Content b", "Write-Output c"]
    assert texts("pytest `\n  -q", 0) == ["pytest `\n  -q"]
    assert shell.parse("[IO.File]::WriteAllText('a', 'b')").pipelines[0].commands[0].words[0].text == "[IO.File]::WriteAllText('a', 'b')"
    assert shell.parse(".\\gradlew.bat test").pipelines[0].commands[0].words[0].text == ".\\gradlew.bat"
    assert shell.head_name(".\\gradlew.bat") == "gradlew"
    assert shell.head_name("C:\\tools\\pytest.exe") == "pytest"


def test_it_is_cut_short_on_purpose():
    assert shell.too_big("a;" * (shell.MAX_PIPELINES + 10))
    assert shell.too_big("a|" * (shell.MAX_PIPELINES + 10))
    assert shell.too_big("x" * (shell.MAX_BYTES + 1))
    assert shell.too_big("(" * (shell.MAX_DEPTH + 10))
    assert shell.too_big("$(" * (shell.MAX_DEPTH + 10))
    assert not shell.too_big("a;" * 100)
    assert len(shell.parse("a " + "b " * (shell.MAX_WORDS + 10)).pipelines[0].commands[0].words) == shell.MAX_WORDS


@pytest.mark.parametrize("src", ["'", '"', "`", "$(", "${", "$((", "(", ")", "{", "}", "<<", "<<<", ">", "|", "&", ";", ";;", "\\", "if", "then", "fi", "for", "for x", "for x in", "case", "case x", "case x in", "while", "function", "function f", "f()", "[[", "((", "!", "! !", "a |", "a &&", "a ||",
                                 "\x00", "\ud800", "<<EOF", "<<'EOF", 'cat <<"', "a > ", "2>", "$'", "$'\\", "\\\n", "`\n", "a=(", "x=$(", "if a; then", "if a; then b; else", "for i in a; do", "case a in (", "case a in b)", "cd", "cd $(", "bash -c", "bash -c '", "eval", "eval '", "echo | bash"])
def test_any_broken_input_is_read_without_raising(src):
    shell.parse(src)
    shell.units(src)
