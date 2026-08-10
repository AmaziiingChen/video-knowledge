from services import campus_source_catalog as catalog
from services import campus_sources


def test_catalog_owns_source_models_and_the_campus_sources_facade_re_exports_them():
    assert campus_sources.CampusSource is catalog.CampusSource
    assert campus_sources.CampusArticle is catalog.CampusArticle
    assert campus_sources.CAMPUS_SOURCES is catalog.CAMPUS_SOURCES

    source = catalog.get_campus_source("sztu")
    assert catalog.campus_source_for_url("https://www.sztu.edu.cn/info/1001/1.htm") == source
    assert catalog.is_campus_article_url("https://www.sztu.edu.cn/info/1001/1.htm")
    assert catalog.is_allowed_campus_host("www.sztu.edu.cn")
    assert not catalog.is_campus_article_url("https://example.test/info/1001/1.htm")
