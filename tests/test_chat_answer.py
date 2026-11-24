from __future__ import annotations

from app.chat.answer import answer_is_grounded
from app.content.snapshot import SnapshotLink
from app.search.hybrid import SearchHit


def test_answer_validator_allows_only_retrieved_phone_and_approved_urls() -> None:
    hit = SearchHit("phone", "contact", 1.0, "Call 08012345678.", 1.0, 1.0)
    link = SnapshotLink(
        link_key="contact",
        kind="contact",
        label="Admissions",
        url="https://zit.edu.gh/admissions",
        description="Contact Admissions",
        aliases=(),
        priority=1,
    )

    assert answer_is_grounded(
        "Call 08012345678. Visit https://zit.edu.gh/admissions.",
        [hit],
        [link],
    )
    assert not answer_is_grounded("Call 08099999999.", [hit], [link])
    assert not answer_is_grounded("Visit https://example.com.", [hit], [link])
