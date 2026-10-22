import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whatisworth.i18n import t  # noqa: E402
from whatisworth.projects import label, resolve_repo  # noqa: E402


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_subdirectory_and_worktree_resolve_to_main_repo(tmp_path):
    main = tmp_path / "my-app"
    (main / "src" / "deep").mkdir(parents=True)
    git("init", "-q", cwd=main)
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x", cwd=main)
    git("worktree", "add", "-q", str(tmp_path / "my-app-feature-wt"), cwd=main)
    assert resolve_repo(str(main / "src" / "deep")) == str(main)
    assert resolve_repo(str(tmp_path / "my-app-feature-wt")) == str(main)
    assert label(str(tmp_path / "my-app-feature-wt"), str(main)) == "my-app"


def test_missing_and_home_directories_fall_back():
    assert resolve_repo("/does/not/exist") is None
    assert label("/does/not/exist/old-feature-wt", None) == "old-feature-wt"
    assert label(str(Path.home()), None) == t("project.home")
