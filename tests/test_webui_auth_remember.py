import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from webui_auth import AuthManager, REMEMBER_SESSION_SECONDS, SHORT_SESSION_SECONDS


def test_remembered_session_survives_auth_manager_restart():
    with tempfile.TemporaryDirectory() as tmp:
        auth_path = Path(tmp) / "auth.json"
        auth = AuthManager(auth_path)
        auth.save("admin", "long-test-password", True)
        sid, csrf = auth.session("admin", remember=True)
        assert auth.session_max_age(sid) == REMEMBER_SESSION_SECONDS
        assert (Path(tmp) / "webui-sessions.json").exists()

        restarted = AuthManager(auth_path)
        session = restarted.authenticate_cookie(f"dantherm_session={sid}")
        assert session is not None
        assert session["username"] == "admin"
        assert session["csrf"] == csrf
        assert session["remember"] is True


def test_short_session_is_not_persisted():
    with tempfile.TemporaryDirectory() as tmp:
        auth_path = Path(tmp) / "auth.json"
        auth = AuthManager(auth_path)
        auth.save("admin", "long-test-password", True)
        sid, _csrf = auth.session("admin", remember=False)
        assert auth.session_max_age(sid) == SHORT_SESSION_SECONDS

        restarted = AuthManager(auth_path)
        assert restarted.authenticate_cookie(f"dantherm_session={sid}") is None
