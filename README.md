# file-tidy

A Claude Code skill (and plain Python CLI) that tidies Desktop, Downloads and photo/video dumps
**without guessing and without losing anything**:

- **Plan first.** Every run is a dry-run plan you can read; `apply` executes exactly that plan.
- **Undo always.** Each apply writes a shell script that moves everything back.
- **Content over filenames.** Files whose names say nothing get opened and classified by what they are.
  For photos, `sheet` builds contact sheets so a person or a vision model can label hundreds at a glance.
- **Hands off what matters.** Git repos, hidden files, symlinks, photo-library packages and files touched
  in the last 10 minutes are never moved. Nothing is ever deleted; duplicates go to `_duplicates/`.
- **No broken links.** `refs` lists notes and scripts that cite a path you are about to move.
- **Your words, your taxonomy.** Category names come from your config, so folders read the way you think.

Python 3.8+, standard library only. Optional: `ffmpeg`/`ffprobe` (video dates, contact sheets);
macOS `mdls`/`sips` are used automatically for photo dates and HEIC thumbnails.

## Install as a Claude Code skill

```sh
git clone https://github.com/<owner>/file-tidy ~/tools/file-tidy
ln -s ~/tools/file-tidy/skills/file-tidy ~/.claude/skills/file-tidy
mkdir -p ~/.config/file-tidy
cp ~/tools/file-tidy/skills/file-tidy/config.example.json ~/.config/file-tidy/config.json   # then edit
```

Then just ask Claude: "tidy my Desktop", "archive old Downloads", "sort these phone photos by month".

## Use the CLI directly

```sh
T=~/tools/file-tidy/skills/file-tidy/scripts/tidy.py
python3 $T plan  --target desktop                    # dry run: counts + UNMATCHED list + plan file
python3 $T plan  --target desktop --labels labels.json   # add your decisions {"file.pdf": "Contracts"}
python3 $T refs  --plan-file <plan.json>             # who cites the paths that will move
python3 $T apply --plan-file <plan.json>             # move + write undo-*.sh
python3 $T sheet --dir ~/Pictures/Inbox              # contact sheets for visual labelling
```

## Modes

| mode | for | result |
|---|---|---|
| `rules` | Desktop, project dumps | top-level items into category folders by filename regex + labels |
| `inbox` | Downloads | loose files older than `keep_days` into `<archive>/<type>/`; subfolders untouched |
| `media` | photo / video dumps | `<dest>/<kind>/<yyyy>/<yyyy-mm>/`; kinds: photos, videos, screenshots, chat; duplicates split out |

Capture date order: embedded metadata (Spotlight / ffprobe) -> date in filename -> file mtime.
The plan reports how many dates came from each source.

## Tests

```sh
python3 -m unittest discover tests
```

MIT licensed.
