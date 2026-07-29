import random
from pydantic import BaseModel
from pythonbible import (
    Book,
    Version,
    get_number_of_chapters,
    get_number_of_verses,
    get_verse_id,
    get_verse_text,

)
from pythonbible.errors import InvalidVerseError




class BibleVerse(BaseModel):
    reference: str
    text: str
    version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "reference": self.reference,
            "text": self.text,
            "version": self.version,
        }


def get_random_verse(
    version: Version = Version.KING_JAMES,
) -> dict[str, str]:
       while True:
        # pick a random book, chapter, verse
        book = random.choice(list(Book))
        chap_count = get_number_of_chapters(book)
        chapter = random.randint(1, chap_count)
        verse_count = get_number_of_verses(book, chapter)
        verse = random.randint(1, verse_count)

        # build verse_id
        vid = get_verse_id(book, chapter, verse)

        # try to fetch text; if missing, loop again
        try:
            text = get_verse_text(vid, version=version)
        except InvalidVerseError:
            continue

        # manually build a human‐readable reference
        # e.g. Book.GENESIS → "Genesis", handle underscores too
        book_name = book.name.replace("_", " ").title()
        reference = f"{book_name} {chapter}:{verse}"

        version_label = version.name.replace("_", " ").title()

        return BibleVerse(
            reference=reference,
            text=text,
            version=version_label,
        ).to_dict()
