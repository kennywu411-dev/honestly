# Security

honestly runs as a hook inside your coding agent: it reads the current session transcript on your machine and, when you run `honestly guard install`, writes its two hook entries into the agent's settings file. It makes no network calls except an optional once-a-day PyPI version check (`HONESTLY_NO_UPDATE_CHECK=1` turns it off) and `pr-note --gh`, which posts to your own pull request.

If you find a way to make honestly execute something it should not, leak transcript content, or damage a settings file, please report it privately through GitHub's "Report a vulnerability" button on the repository's Security tab rather than in a public issue. You will get a reply within a few days.
