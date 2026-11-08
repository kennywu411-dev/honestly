"""Windows runs a program from the current directory before System32, so a repository's powershell.exe would win. A PATH with an empty entry does the same on POSIX."""
import os
import stat
import sys

import pytest

from honestly import programs, prnote


def _make(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text("")
    os.chmod(p, stat.S_IRWXU)
    return str(p)


def test_on_windows_the_current_directory_is_not_searched(tmp_path, monkeypatch):
    repo, system = tmp_path / "repo", tmp_path / "system32"
    _make(repo, "powershell.exe")
    real = _make(system, "powershell.exe")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PATH", os.pathsep.join([str(repo), ".", "", str(system)]))
    monkeypatch.setenv("PATHEXT", ".exe;.cmd")
    assert programs.program("powershell", windows=True) == real


def test_on_windows_a_program_only_in_the_current_directory_is_not_run(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _make(repo, "git.exe")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("PATHEXT", ".exe")
    with pytest.raises(FileNotFoundError):
        programs.program("git", windows=True)


def test_on_posix_a_clean_path_is_left_to_the_system():
    assert programs.program("git", windows=False) == "git" or os.environ.get("PATH", "").split(os.pathsep).count("") or "." in os.environ.get("PATH", "").split(os.pathsep)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PATH rules")
def test_on_posix_an_empty_path_entry_does_not_reach_the_current_directory(tmp_path, monkeypatch):
    repo, bin_dir = tmp_path / "repo", tmp_path / "bin"
    _make(repo, "git")
    real = _make(bin_dir, "git")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PATH", os.pathsep.join(["", str(bin_dir)]))
    assert programs.program("git", windows=False) == real


@pytest.mark.skipif(os.name != "nt", reason="the real thing, on Windows")
def test_the_real_search_skips_a_planted_program(tmp_path, monkeypatch):
    (tmp_path / "powershell.exe").write_text("")
    monkeypatch.chdir(tmp_path)
    assert os.path.dirname(os.path.realpath(programs.program("powershell"))) != os.path.realpath(str(tmp_path))


def test_git_goes_through_it(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(prnote, "program", lambda name: seen.append(name) or name)
    prnote._git(["--version"], str(tmp_path))
    assert seen == ["git"]
