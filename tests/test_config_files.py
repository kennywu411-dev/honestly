"""A config file is data from a repository. Whatever it is, reading it stays cheap and the guard stays on."""
import json
import os
import signal
import sys

import pytest

from honestly import config

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX devices and FIFOs")


@pytest.fixture
def alarm():
    if sys.platform == "win32":
        yield
        return
    def boom(*a):
        raise TimeoutError("reading the config did not return")
    old = signal.signal(signal.SIGALRM, boom)
    signal.setitimer(signal.ITIMER_REAL, 0.5)
    yield
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, old)


@posix_only
def test_a_symlink_to_an_endless_device_is_ignored(tmp_path, alarm):
    p = tmp_path / ".honestly.json"
    os.symlink("/dev/zero", p)
    assert config._read(str(p)) == {}


@posix_only
def test_a_fifo_is_ignored_without_blocking(tmp_path, alarm):
    p = tmp_path / ".honestly.json"
    os.mkfifo(p)
    assert config._read(str(p)) == {}


def test_a_huge_file_is_ignored(tmp_path):
    p = tmp_path / ".honestly.json"
    p.write_text('{"ignore": ["' + "a" * (2 * config.MAX_CONFIG_BYTES) + '"]}')
    assert config._read(str(p)) == {}


def test_a_directory_and_a_missing_file_are_ignored(tmp_path):
    (tmp_path / "d").mkdir()
    assert config._read(str(tmp_path / "d")) == {}
    assert config._read(str(tmp_path / "missing")) == {}


def test_bad_encoding_and_bad_json_are_ignored(tmp_path):
    p = tmp_path / "c.json"
    p.write_bytes(b"\xff\xfe{")
    assert config._read(str(p)) == {}
    p.write_text("{oops")
    assert config._read(str(p)) == {}
    p.write_text("[1, 2]")
    assert config._read(str(p)) == {}


def test_an_ordinary_file_still_reads(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"strictness": "strict"}), encoding="utf-8")
    assert config._read(str(p)) == {"strictness": "strict"}


@posix_only
def test_a_symlink_to_a_real_config_still_reads(tmp_path):
    real = tmp_path / "dotfiles.json"
    real.write_text('{"language": "zh"}')
    link = tmp_path / "config.json"
    os.symlink(real, link)
    assert config._read(str(link)) == {"language": "zh"}
