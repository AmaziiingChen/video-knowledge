from services.campus_digest_identity import (
    canonical_url,
    normalize_identity,
    source_hash,
    text_shingle_similarity,
)


def test_source_identity_normalizes_share_urls_and_text_deterministically():
    assert canonical_url("HTTPS://Example.COM/a/?from=share&keep=1#fragment") == "https://example.com/a?keep=1"
    assert normalize_identity(" 深圳 技术大学－2026！ ") == "深圳技术大学2026"
    assert source_hash("同一来源") == source_hash("同一来源")
    assert source_hash("同一来源") != source_hash("另一来源")
    assert text_shingle_similarity("校园人工智能大会报道", "校园人工智能大会报道") == 1.0
    assert text_shingle_similarity("校园人工智能大会报道", "完全不同的内容") == 0.0
