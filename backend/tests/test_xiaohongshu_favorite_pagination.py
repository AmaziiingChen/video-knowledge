import pytest
from services import xiaohongshu_client
from services.xiaohongshu_capability import XiaohongshuCollectorUnavailable


def test_xiaohongshu_favorite_preview_is_explicitly_outside_the_clean_room_slice():
    with pytest.raises(XiaohongshuCollectorUnavailable, match="主动导入单篇图文"):
        xiaohongshu_client.fetch_my_favorites_preview(limit=50)


def test_xiaohongshu_favorite_sync_is_explicitly_outside_the_clean_room_slice():
    with pytest.raises(XiaohongshuCollectorUnavailable, match="收藏"):
        xiaohongshu_client.fetch_my_favorites(limit=5)
