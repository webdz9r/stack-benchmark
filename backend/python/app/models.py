"""Request bodies and their validation; same rules as the Rust backend."""

from pydantic import BaseModel, StrictBool, StrictInt

from .errors import AppError

TAG_COLORS = ("slate", "red", "orange", "amber", "green", "teal", "sky", "indigo", "violet", "pink")


class LabeledValue(BaseModel):
    label: str = ""
    value: str = ""  # missing counts as empty, so validation drops the row (API-U1)


class Address(BaseModel):
    label: str = ""
    street: str = ""
    city: str = ""
    region: str = ""
    postal_code: str = ""
    country: str = ""

    def is_blank(self) -> bool:
        return not any(
            s.strip() for s in (self.street, self.city, self.region, self.postal_code, self.country)
        )


class ContactInput(BaseModel):
    first_name: str = ""
    last_name: str = ""
    company: str = ""
    job_title: str = ""
    birthday: str | None = None
    notes: str = ""
    favorite: StrictBool = False
    emails: list[LabeledValue] = []
    phones: list[LabeledValue] = []
    addresses: list[Address] = []
    tag_ids: list[StrictInt] = []

    def validated(self) -> "ContactInput":
        """Trim fields, drop empty rows, and reject obviously bad input."""
        for field in ("first_name", "last_name", "company", "job_title", "notes"):
            setattr(self, field, getattr(self, field).strip())
        if not (self.first_name or self.last_name or self.company):
            raise AppError.validation("a name or company is required")

        self.birthday = (self.birthday or "").strip() or None
        if self.birthday and not _is_iso_date(self.birthday):
            raise AppError.validation("birthday must be YYYY-MM-DD")

        for rows in (self.emails, self.phones):
            rows[:] = [r for r in rows if r.value.strip()]
            for r in rows:
                r.value = r.value.strip()
                r.label = _normalize_label(r.label)
        for e in self.emails:
            user, at, domain = e.value.partition("@")
            if not (at and user and "." in domain and not any(ch.isspace() for ch in e.value)):
                raise AppError.validation(f"'{e.value}' is not a valid email")

        self.addresses = [a for a in self.addresses if not a.is_blank()]
        for a in self.addresses:
            a.label = _normalize_label(a.label)
            for field in ("street", "city", "region", "postal_code", "country"):
                setattr(a, field, getattr(a, field).strip())

        self.tag_ids = sorted(set(self.tag_ids))
        return self


class TagInput(BaseModel):
    name: str
    color: str | None = None

    def validated(self) -> "TagInput":
        self.name = self.name.strip()
        if not self.name:
            raise AppError.validation("tag name is required")
        if len(self.name) > 40:
            raise AppError.validation("tag name must be 40 characters or fewer")
        if self.color is not None and self.color not in TAG_COLORS:
            raise AppError.validation(f"unknown tag color '{self.color}'")
        return self


class FavoriteBody(BaseModel):
    favorite: StrictBool


def _normalize_label(label: str) -> str:
    return label.strip().lower() or "other"


def _is_iso_date(s: str) -> bool:
    parts = s.split("-")
    if len(parts) != 3 or [len(p) for p in parts] != [4, 2, 2] or not all(p.isdigit() for p in parts):
        return False
    return 1 <= int(parts[1]) <= 12 and 1 <= int(parts[2]) <= 31
