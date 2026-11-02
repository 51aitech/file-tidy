---
name: file-tidy
description: Tidy messy folders (Desktop, Downloads, photo/video dumps) with a reviewable plan, content-aware classification and a one-command undo. Use when the user asks to organize, sort, clean up or archive files or folders, sort photos or videos by date, find duplicate photos, or set up a recurring Downloads clean-up.
---

# file-tidy

The script does the mechanical, risky part (planning, moving, never overwriting, undo, finding stale references).
You do the part a script cannot: deciding where a file belongs when its name does not say.

Script: `scripts/tidy.py` (Python 3.8+, stdlib only; optional `ffprobe` for video dates; macOS Spotlight used for photo dates when present).

## Workflow

1. **Read the user's taxonomy first.** Config is `~/.config/file-tidy/config.json` (start from `config.example.json`).
   If the user already has a filing system (a notes vault, a project list, a code/ID registry), mirror its categories
   instead of inventing new ones, and ask where it is if you cannot find it. Folder names the user reads must be
   words they recognise; IDs or codes, if any, go after the word (`Invoices INV`), never alone.
2. **Plan (dry run).** `python3 scripts/tidy.py plan --target <name>` prints counts per destination and every
   `UNMATCHED` item, and saves a plan JSON. Nothing has moved yet.
3. **Classify the unmatched by content, not by name.** Open each one: read images and PDFs, peek at docs. Decide by
   what the file *is* (the product, the person, the trip), not by who issued it. Write the decisions to a labels JSON
   `{"filename": "Category"}` and plan again with `--labels`. Only ask the user about items that stay ambiguous
   after you have looked inside them.
4. **Check references.** `python3 scripts/tidy.py refs --plan-file <plan>` lists notes/scripts under `refs_roots`
   that cite a path about to move. Update those citations in the same pass (they also catch multi-line or
   relative mentions only partially, so grep for distinctive filenames too).
5. **Show the plan, then apply.** For a first run in a folder, or anything personal (photos, IDs), show the counts
   and sample moves and get a yes. `python3 scripts/tidy.py apply --plan-file <plan>` executes exactly that plan and
   writes `undo-*.sh` next to it. Tell the user the undo path.
6. **Verify.** List the result, confirm protected items (git repos, recent files, keep-rules) are still in place.

## Modes

| mode | for | behaviour |
|---|---|---|
| `rules` | Desktop, project dumps | top-level items -> category folders by filename regex + your labels |
| `inbox` | Downloads | loose files older than `keep_days` -> `<archive>/<type>/`; subfolders untouched |
| `media` | photo/video dumps, phone exports | `<dest>/<kind>/<yyyy>/<yyyy-mm>/`; kinds = photos, videos, screenshots, chat; exact duplicates -> `_duplicates/` |

Media date source order: embedded capture date (Spotlight / ffprobe) -> date in the filename -> file mtime. The plan
prints how many came from each; a high mtime count means dates are guesses, say so.

## Photos and videos: personal vs work

`media` mode sorts by kind and date only. If the dump mixes personal and work pictures, look at them in batches
(make a contact sheet with ffmpeg: `ffmpeg -i "%03d.jpg"`-style input or a montage per month folder) and label the
work ones (`{"IMG_1234.HEIC": "work"}`), then re-plan; labels replace the kind in the layout.
Never move anything inside a photo-library package (`*.photoslibrary`); the script skips them.

## Never

- Never delete. Duplicates are moved to `_duplicates/` for the user to review and empty.
- Never move a folder containing `.git`, hidden files, symlinks, or files modified in the last 10 minutes (script enforces).
- Never apply a plan you have not shown counts for, and never edit a plan JSON by hand to sneak moves in.
- Never put business names, personal data or paths of the user into this skill folder; they belong in the user's config.

## Recurring Downloads clean-up

`inbox` mode has no judgment step, so it can run unattended (cron/launchd), e.g. daily:
`python3 tidy.py plan --target downloads && python3 tidy.py apply --plan-file "$(ls -t ~/.local/state/file-tidy/plan-downloads-*.json | head -1)"`.
