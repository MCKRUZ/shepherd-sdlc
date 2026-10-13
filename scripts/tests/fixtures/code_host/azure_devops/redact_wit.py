"""Redact a captured Boards discussion document before it becomes a fixture (pure; no I/O in `redact_wit`).

Usage:  python redact.py --org contoso < captured.json | python redact_wit.py > fixture.json

`redact.py` swaps GUIDs, e-mail addresses and the organisation for stable fakes, but it cannot see what a
person typed. This is the second stage. It removes what is left in a comment or a work item's history:

  * `text`, `renderedText` and `commentVersionRef.text`, and every value under `System.History` (a string,
    an `oldValue`/`newValue` pair, or the `value` of a patch op on that field), become `REDACTED_TEXT`;
  * `mentions[].targetId` — the id of the person mentioned, in whatever form the API used — becomes an
    anonymised GUID, the same one for the same raw id;
  * `createdOnBehalfOf` is scrubbed: a bare name or an identity without a `uniqueName` becomes
    `REDACTED_IDENTITY`; an identity with one is treated like every other;
  * beside any `uniqueName` the `displayName` becomes `Participant N`, where N is the number of the stand-in
    address `personN@example.com`; the same dict's `descriptor`, `subjectDescriptor`, `imageUrl` and avatar
    `_links` become the `aad.anonymised-N` forms the hand-written fixtures use.

It is safe without `redact.py` in front of it. Every other string is swept: any e-mail address that is not
already `personN@example.com` becomes one (a leading `@` glued to it, as in a mention, is dropped), and any
GUID that is not already `00000000-0000-0000-0000-NNNNNNNNNNNN` becomes one. Numbers are handed out in the
order a value first appears and skip every number the document already uses, so the output is deterministic
and redacting it again changes nothing. Keys, list lengths and every other value are preserved, so a mapper
written against the hand-written fixtures reads the captured ones unchanged. Not touched: the organisation
name (`redact.py --org` owns it) and work item fields other than History (titles are the client's to review
before anything is committed).

Standard library only: it runs as a script from anywhere, so it imports nothing of the plugin's.
"""

import argparse
import itertools
import json
import re
import sys

REDACTED_TEXT = "[redacted: free text]"
REDACTED_IDENTITY = "[redacted: identity]"

FREE_TEXT_KEYS = frozenset({"text", "renderedText"})
HISTORY_FIELD = "System.History"
DESCRIPTOR_KEYS = frozenset({"descriptor", "subjectDescriptor"})
AVATAR_PREFIX = "https://dev.azure.com/contoso/_apis/GraphProfile/MemberAvatars/aad.anonymised-"

_EMAIL = re.compile(r"(@?)([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
_GUID = re.compile(r"(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
                   r"(?![0-9A-Fa-f-])")
_FAKE_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])person(\d+)@example\.com(?![A-Za-z0-9-])", re.IGNORECASE)
_ANON_GUID = re.compile(r"00000000-0000-0000-0000-(\d{12})")


class _Numbers:
    """Hands out the smallest unused positive integer per key, remembering each key's number."""

    def __init__(self, used):
        self._used = set(used)
        self._by_key: dict[str, int] = {}

    def number(self, key: str) -> int:
        if key not in self._by_key:
            n = next(i for i in itertools.count(1) if i not in self._used)
            self._used.add(n)
            self._by_key[key] = n
        return self._by_key[key]


def _strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def _mask(value):
    """A non-empty string becomes the text marker; anything else (None, "", a number) is left."""
    return REDACTED_TEXT if isinstance(value, str) and value else value


def _mask_all(value):
    if isinstance(value, dict):
        return {k: _mask_all(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_all(v) for v in value]
    return _mask(value)


def _avatar_links(value, url: str):
    if isinstance(value, dict):
        return {k: (url if k == "href" and isinstance(v, str) else _avatar_links(v, url)) for k, v in value.items()}
    if isinstance(value, list):
        return [_avatar_links(v, url) for v in value]
    return value


class _Redactor:
    def __init__(self, doc):
        text = list(_strings(doc))
        self.people = _Numbers(int(m.group(1)) for s in text for m in _FAKE_EMAIL.finditer(s))
        self.guids = _Numbers(int(m.group(1)) for s in text for m in _ANON_GUID.finditer(s))

    # values ---------------------------------------------------------------------------------------------

    def fake_email(self, address: str) -> str:
        if _FAKE_EMAIL.fullmatch(address):
            return address
        return f"person{self.people.number(address.lower())}@example.com"

    def fake_guid(self, raw: str) -> str:
        if _ANON_GUID.fullmatch(raw):
            return raw
        return f"00000000-0000-0000-0000-{self.guids.number(raw.lower()):012d}"

    def sweep(self, text: str) -> str:
        text = _EMAIL.sub(lambda m: self.fake_email(m.group(2)), text)
        return _GUID.sub(lambda m: self.fake_guid(m.group(0)), text)

    # structure ------------------------------------------------------------------------------------------

    def walk(self, value):
        if isinstance(value, dict):
            return self.mapping(value)
        if isinstance(value, list):
            return [self.walk(v) for v in value]
        if isinstance(value, str):
            return self.sweep(value)
        return value

    def mapping(self, node: dict) -> dict:
        unique = node.get("uniqueName")
        who = None  # N, the number of this identity's stand-in address
        if isinstance(unique, str) and unique:
            stand_in = self.fake_email(unique)
            who = int(_FAKE_EMAIL.fullmatch(stand_in).group(1))
        out = {}
        for key, value in node.items():
            if who is not None and key == "uniqueName":
                out[key] = stand_in
            elif who is not None and key == "displayName" and isinstance(value, str):
                out[key] = f"Participant {who}"
            elif who is not None and key in DESCRIPTOR_KEYS and isinstance(value, str):
                out[key] = f"aad.anonymised-{who}"
            elif who is not None and key == "imageUrl" and isinstance(value, str):
                out[key] = AVATAR_PREFIX + str(who)
            elif who is not None and key == "_links":
                out[key] = _avatar_links(value, AVATAR_PREFIX + str(who))
            elif key in FREE_TEXT_KEYS and (value is None or isinstance(value, str)):
                out[key] = _mask(value)
            elif key == HISTORY_FIELD:
                out[key] = _mask_all(value)
            elif key == "mentions" and isinstance(value, list):
                out[key] = [self.mention(item) for item in value]
            elif key == "createdOnBehalfOf":
                out[key] = self.on_behalf(value)
            else:
                out[key] = self.walk(value)
        path = node.get("path")
        if isinstance(path, str) and path.endswith("/" + HISTORY_FIELD) and "value" in node:
            out["value"] = _mask_all(node["value"])  # a patch op on the History field
        return out

    def mention(self, item):
        if not isinstance(item, dict):
            return self.walk(item)
        return {k: (self.fake_guid(v) if k == "targetId" and isinstance(v, str) and v else self.walk(v))
                for k, v in item.items()}

    def on_behalf(self, value):
        if isinstance(value, str):
            return REDACTED_IDENTITY if value else value
        if isinstance(value, dict) and not (isinstance(value.get("uniqueName"), str) and value["uniqueName"]):
            return {k: (REDACTED_IDENTITY if k == "displayName" and isinstance(v, str) and v else self.walk(v))
                    for k, v in value.items()}
        return self.walk(value)


def redact_wit(doc):
    """Return a redacted copy of `doc` (any JSON value); `doc` itself is never changed."""
    return _Redactor(doc).walk(doc)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="redact_wit.py",
        description="Second-stage redactor for a captured Boards discussion document: reads JSON on stdin "
                    "(after redact.py), writes the redacted JSON on stdout.")
    parser.parse_args(argv)
    try:
        doc = json.load(sys.stdin)
    except ValueError:
        print("redact_wit: stdin is not a JSON document", file=sys.stderr)
        return 1
    json.dump(redact_wit(doc), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
