import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whatisworth.i18n import t  # noqa: E402
from whatisworth.projects import known_repo, label, load_rules, resolve_repo  # noqa: E402


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


def test_deleted_subdirectory_inherits_repo_of_known_ancestor():
    repos = {"/work/my-app": "/work/my-app", "/work": None}
    assert known_repo("/work/my-app/gone/deeper", repos) == "/work/my-app"
    assert known_repo("/work/old-feature-wt", repos) is None


def test_rules_map_deleted_worktrees_and_their_subdirectories(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text('{"/work/my-app-*": "my-app"}')
    rules = load_rules(path)
    assert label("/work/my-app-feature-wt/src/deep", None, rules) == "my-app"
    assert label("/work/other-wt", None, rules) == "other-wt"
    assert load_rules(tmp_path / "missing.json") == []
