import pytest

from services import xiaohongshu_client


def _entry(note_id: str) -> dict:
    return {
        "id": note_id,
        "xsec_token": "token",
        "note_card": {
            "title": f"笔记 {note_id}",
            "desc": "摘要",
            "user": {"nickname": "作者", "user_id": "owner", "avatar": ""},
            "image_list": [],
            "interact_info": {},
            "tag_list": [],
            "time": 1_700_000_000_000,
        },
    }


def test_xiaohongshu_favorite_preview_follows_cursors_up_to_the_explicit_limit(monkeypatch):
    requested_user_ids = []

    class Api:
        def get_user_me(self):
            return True, "", {"data": {"user_id": "self-id", "nickname": "我"}}

        def get_user_collect_note_info(self, _user_id, cursor, **_kwargs):
            requested_user_ids.append(_user_id)
            if not cursor:
                return True, "", {"data": {"notes": [_entry("one"), _entry("two")], "cursor": "next", "has_more": True}}
            return True, "", {"data": {"notes": [_entry("three")], "cursor": "", "has_more": False}}

    monkeypatch.setattr(xiaohongshu_client, "_api", lambda: Api())

    notes, account = xiaohongshu_client.fetch_my_favorites_preview(limit=3)

    assert account["user_id"] == "self-id"
    assert [note.note_id for note in notes] == ["one", "two", "three"]
    assert requested_user_ids == ["self-id", "self-id"]


def test_xiaohongshu_favorite_preview_queries_the_profile_id_from_the_pasted_link(monkeypatch):
    requested_user_ids = []

    class Api:
        def get_user_me(self):
            return True, "", {"data": {"user_id": "api-account", "nickname": "我"}}

        def get_user_collect_note_info(self, user_id, _cursor, **_kwargs):
            requested_user_ids.append(user_id)
            return True, "", {"data": {"notes": [], "cursor": "", "has_more": False}}

    monkeypatch.setattr(xiaohongshu_client, "_api", lambda: Api())

    notes, account = xiaohongshu_client.fetch_my_favorites_preview(
        limit=50,
        profile_user_id="profile-page-id",
    )

    assert notes == []
    assert account["user_id"] == "api-account"
    assert account["collection_user_id"] == "profile-page-id"
    assert requested_user_ids == ["profile-page-id"]


def test_xiaohongshu_favorite_preview_rejects_a_guest_cookie(monkeypatch):
    class Api:
        def get_user_me(self):
            return True, "", {"data": {"user_id": "guest-id", "guest": True}}

    monkeypatch.setattr(xiaohongshu_client, "_api", lambda: Api())

    with pytest.raises(xiaohongshu_client.XiaohongshuClientError, match="访客会话"):
        xiaohongshu_client.fetch_my_favorites_preview(limit=50, profile_user_id="profile-page-id")
