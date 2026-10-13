"""PDF 에서 그림자·굵게 효과로 겹쳐 그린 글자의 사본을 걸러낸다(2026-10-13)."""

from apps.api.app.services import document_extraction
from apps.api.app.services.document_extraction import _drop_shadow_copies, _pdf_page_text


def _shadowed(text: str, x: float, y: float, size: float, copies: int) -> list[tuple[str, float, float, float]]:
    """한컴 PDF 의 입체 글자처럼, 한 단위씩 어긋난 자리에 같은 글자를 여러 번 그린다."""
    return [(text, x + step, y + step, size) for step in range(copies)]


def test_shadow_copies_of_a_title_collapse_to_one_glyph_each() -> None:
    chunks = [
        *_shadowed("제 ", 1788, 1532, 208, 18),
        *_shadowed("안 ", 2100, 1532, 208, 18),
        ("\n", 0, 0, 208),
        *_shadowed("용역", 1500, 900, 120, 3),      # 굵게 흉내(세 번 겹쳐 그림)
    ]
    kept, dropped = _drop_shadow_copies(chunks)
    assert "".join(kept) == "제 안 \n용역"
    assert dropped == 17 + 17 + 2


def test_repeated_words_that_are_really_there_are_kept() -> None:
    chunks = [
        ("개발", 100, 500, 10), ("개발", 130, 500, 10),          # 같은 줄에 나란히 두 번(반 글자 넘게 떨어짐)
        ("개발", 100, 480, 10),                                  # 다음 줄의 같은 낱말
        (" 및", 0, 0, 10), (" 및", 0, 0, 10), (" 및", 0, 0, 10),  # 자리를 모르는 조각은 건드리지 않는다
        (" ", 100, 500, 10), (" ", 100, 500, 10),                # 공백도 건드리지 않는다
    ]
    kept, dropped = _drop_shadow_copies(chunks)
    assert dropped == 0 and kept == [text for text, *_ in chunks]


def test_page_text_is_untouched_unless_the_page_has_shadow_copies(monkeypatch) -> None:
    class Page:
        def __init__(self, chunks, plain):
            self.chunks, self.plain = chunks, plain

        def extract_text(self, visitor_text=None):
            for text, x, y, size in self.chunks:
                visitor_text(text, None, [1, 0, 0, 1, x, y], None, size)
            return self.plain

    # 겹친 사본이 한두 개뿐이면(우연히 가까운 같은 글자) pypdf 가 준 글을 그대로 쓴다.
    ordinary = Page([("가", 10, 10, 10), ("가", 10.5, 10, 10), ("나", 40, 10, 10)], "pypdf 가 준 글")
    assert _pdf_page_text(ordinary) == "pypdf 가 준 글"
    cover = Page(_shadowed("서 ", 500, 700, 200, 18), "서 " * 18)
    assert _pdf_page_text(cover) == "서 "
    assert document_extraction._SHADOW_MIN_COPIES == 3
