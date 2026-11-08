"""Drive a real TUI in a pty and read its screen: used for flows `-p`/`exec` do not show (Codex /hooks review, Claude Code's interactive stop message)."""
import fcntl, os, pty, re, select, signal, struct, termios, time
import pyte

class TUI:
    def __init__(self, argv, env, cwd, rows=50, cols=160):
        self.screen = pyte.Screen(cols, rows); self.stream = pyte.ByteStream(self.screen)
        self.raw = b""
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(cwd)
            os.execvpe(argv[0], argv, env)
        self.pid, self.fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def pump(self, secs=1.0):
        end = time.time() + secs
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.1)
            if not r:
                continue
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                return False
            if not data:
                return False
            self.raw += data
            if b"\x1b[6n" in data:   # answer the terminal queries a TUI waits on
                os.write(self.fd, f"\x1b[{self.screen.cursor.y + 1};{self.screen.cursor.x + 1}R".encode())
            if b"\x1b[c" in data or b"\x1b[0c" in data:
                os.write(self.fd, b"\x1b[?62c")
            if b"\x1b]10;?" in data:
                os.write(self.fd, b"\x1b]10;rgb:ffff/ffff/ffff\x1b\\")
            if b"\x1b]11;?" in data:
                os.write(self.fd, b"\x1b]11;rgb:0000/0000/0000\x1b\\")
            self.stream.feed(data)
        return True

    def text(self):
        return "\n".join(l.rstrip() for l in self.screen.display).strip()

    def send(self, s):
        os.write(self.fd, s.encode() if isinstance(s, str) else s)

    def wait_for(self, pattern, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.5)
            if re.search(pattern, self.text()):
                return True
        return False

    def close(self):
        try:
            os.kill(self.pid, signal.SIGKILL); os.waitpid(self.pid, 0)
        except Exception:
            pass
