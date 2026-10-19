"""Domain name validation and normalization."""

import re

import idna

_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


class InvalidDomainName(ValueError):
    pass


def normalize_domain_name(raw: str) -> str:
    """Return the canonical ASCII (punycode), lower-case form of a registrable domain name.

    Accepts common copy/paste noise: surrounding whitespace, a URL scheme, a path,
    a trailing dot and a leading ``www.`` is *not* stripped (it may be intentional).
    """
    if raw is None:
        raise InvalidDomainName("Domain name is required.")
    value = raw.strip().lower()
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value)  # scheme
    value = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in value:
        raise InvalidDomainName("Domain name must not contain '@'.")
    if ":" in value:
        raise InvalidDomainName("Domain name must not include a port.")
    value = value.rstrip(".")
    if not value:
        raise InvalidDomainName("Domain name is required.")

    try:
        ascii_name = idna.encode(value, uts46=True).decode("ascii")
    except idna.IDNAError as exc:
        raise InvalidDomainName(f"Invalid internationalized domain name: {exc}") from None

    if len(ascii_name) > 253:
        raise InvalidDomainName("Domain name is longer than 253 characters.")
    labels = ascii_name.split(".")
    if len(labels) < 2:
        raise InvalidDomainName("Domain name must include a top-level domain (e.g. example.com).")
    for label in labels:
        if not _LABEL_RE.match(label):
            raise InvalidDomainName(f"Invalid domain label: '{label}'.")
    tld = labels[-1]
    if tld.isdigit():
        raise InvalidDomainName("Top-level domain cannot be numeric.")
    return ascii_name


def display_domain_name(normalized: str) -> str:
    """Unicode form for display, falling back to the ASCII form."""
    try:
        return idna.decode(normalized)
    except idna.IDNAError:
        return normalized


def tld_of(normalized: str) -> str:
    return normalized.rsplit(".", 1)[-1]
