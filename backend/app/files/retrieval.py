"""Deterministic, bounded read-only retrieval from managed SQLite records."""

import heapq
import re

from backend.app.files.contracts import (
    FileSelection, MAX_CONTEXT_CHUNKS, MAX_CONTEXT_CHARS, MAX_FILE_REFS,
)
from backend.app.files import storage

STOP_WORDS = frozenset("a an and are as at be can did do does file files for from has have i in is it me my of on or please say says show tell that the this to uploaded was we what with you about".split())


def search_terms(query):
    """A handful of literal terms, not a semantic search or generated query."""
    return list(dict.fromkeys(term for term in re.findall(r"\w+", (query or "").casefold())
                              if term not in STOP_WORDS))[:12]


def detect_file_reference(connection, owner_id, message, recent_refs=()):
    """Metadata-only detection before routing. Duplicate names require clarification."""
    folded = message.casefold()
    query = " ".join(search_terms(message))[:300] or None
    # A specific ID disambiguates even when the user also types a duplicate name.
    ids = list(dict.fromkeys(re.findall(r"(?<!\w)file_[a-f0-9]{32}(?!\w)", message)))
    if ids:
        return {"selection": FileSelection(file_ids=ids[:MAX_FILE_REFS], query=query).model_dump(), "method": "explicit_id"}
    matches = []
    for item in storage.iter_metadata(connection, owner_id):
        name = item["filename"].casefold()
        if re.search(rf"(?<![\w/\\.:-]){re.escape(name)}(?![\w/\\:-]|\.[\w/\\.-])", folded):
            matches.append(item)
    if matches:
        grouped = {}
        for item in matches:
            grouped.setdefault(item["filename"].casefold(), []).append(item)
        resolved = []
        used_recent = False
        for group in grouped.values():
            if len(group) == 1:
                resolved.append(group[0])
                continue
            # Only a unique, owner-verified reference from this chat can decide
            # between duplicates. Upload order/most-recent timestamp is not identity.
            referenced = [item for item in group if item["file_id"] in recent_refs]
            if len(referenced) != 1:
                return {"selection": FileSelection(filename=group[0]["filename"], query=query).model_dump(),
                        "method": "ambiguous_filename", "filenames": [group[0]["filename"]]}
            resolved.append(referenced[0])
            used_recent = True
        return {"selection": FileSelection(file_ids=[item["file_id"] for item in resolved[:MAX_FILE_REFS]], query=query).model_dump(),
                "method": "filename_chat_reference" if used_recent else "exact_filename",
                "filenames": [item["filename"] for item in resolved[:MAX_FILE_REFS]]}
    # Preserve safe no-match behavior for an explicitly named but unknown file.
    unknown = re.search(r"(?<![\w/\\.:-])([\w-][\w.-]*\.(?:txt|pdf|docx))(?![\w/\\:-]|\.[\w/\\.-])", message, re.I)
    if unknown:
        return {"selection": FileSelection(filename=unknown.group(1), query=query).model_dump(),
                "method": "unknown_filename", "filenames": [unknown.group(1)]}
    refs = list(dict.fromkeys(recent_refs))
    if len(refs) == 1 and re.search(r"\b(?:that (?:pdf|file|document)|the assignment file)\b", folded):
        return {"selection": FileSelection(file_ids=refs, query=query).model_dump(), "method": "recent_file_reference"}
    return None


def _score(chunk, query, terms):
    text, name = chunk["text"].casefold(), chunk["filename"].casefold()
    return (25 * bool(query and query.casefold() in text)
            + sum(8 * (term in text) + min(text.count(term), 3) + 4 * (term in name) for term in terms))


def retrieve_file_context(connection, owner_id, selection):
    """Return at most five chunks / 8,000 text characters; never write or open paths."""
    selected = FileSelection.model_validate(selection)
    if not isinstance(owner_id, str) or not owner_id:
        return {"status": "unavailable", "count": 0, "files": [], "chunks": []}
    file_ids = selected.file_ids
    if selected.filename:
        named = []
        for item in storage.iter_metadata(connection, owner_id):
            if item["filename"].casefold() == selected.filename.casefold():
                named.append(item)
                if len(named) > MAX_FILE_REFS:
                    break
        if len(named) > 1:
            return {"count": 0, "files": named, "chunks": [], "ambiguous": True,
                    "truncated": len(named) > MAX_FILE_REFS,
                    "reason": "Multiple uploads have this filename. Ask which file_id to use."}
        file_ids = [item["file_id"] for item in named]
        if not file_ids:
            return {"count": 0, "files": [], "chunks": [], "truncated": False, "reason": "No matching managed file."}
    terms = search_terms(selected.query)
    if not file_ids and not terms:
        return {"count": 0, "files": [], "chunks": [], "truncated": False, "reason": "No meaningful search terms."}
    candidates = storage.matching_chunks(connection, owner_id, file_ids=file_ids, terms=terms)
    ranked = heapq.nsmallest(MAX_CONTEXT_CHUNKS + 1, (chunk for chunk in candidates if chunk["text"].strip()),
                            key=lambda chunk: (-_score(chunk, selected.query, terms), chunk["file_id"], chunk["position"]))
    chosen, files, budget = [], {}, MAX_CONTEXT_CHARS
    for file_id in file_ids:
        metadata = storage.get_file(connection, owner_id, file_id, include_content=False)
        if metadata is not None:
            files[file_id] = metadata
    truncated = len(ranked) > MAX_CONTEXT_CHUNKS
    for chunk in ranked[:MAX_CONTEXT_CHUNKS]:
        if not budget:
            truncated = True
            break
        text = chunk["text"][:budget]
        truncated |= len(text) < len(chunk["text"])
        budget -= len(text)
        files[chunk["file_id"]] = {key: chunk[key] for key in ("file_id", "filename", "file_type", "created_at", "chunk_count")}
        chosen.append({key: chunk[key] for key in ("file_id", "chunk_id", "position", "page", "section")} | {"text": text})
    # Reading order after relevance selection makes excerpts easier to interpret.
    chosen.sort(key=lambda item: (item["file_id"], item["position"]))
    return {"count": len(chosen), "files": list(files.values()), "chunks": chosen,
            "truncated": truncated, "reason": "Selected literal keyword matches." if chosen else "No matching managed file content."}
