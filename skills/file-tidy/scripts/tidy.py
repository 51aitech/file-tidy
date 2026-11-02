#!/usr/bin/env python3
"""file-tidy: plan -> review -> apply -> undo for messy folders.

Modes (one per target in the config):
  rules  top-level items sorted into category folders by filename regex (+ labels from a human/AI)
  inbox  loose files older than N days moved to <archive>/<type>/ ; subfolders untouched
  media  photos/videos sorted by capture date into <dest>/<kind>/<yyyy>/<yyyy-mm>/ ; exact duplicates split out

Safety: dry-run plan first; apply only executes a saved plan; every apply writes an undo script;
never touches hidden files, symlinks, git repos, or files modified in the last 10 minutes;
never overwrites (name clash -> " (2)" suffix). Python 3.8+ stdlib only.
"""
import argparse, datetime as dt, hashlib, json, os, re, shlex, subprocess, sys, time

TYPES = {
    "images": "jpg jpeg png heic heif gif webp avif bmp tif tiff svg raw dng cr2 nef arw",
    "videos": "mp4 mov m4v avi mkv webm 3gp",
    "pdf": "pdf",
    "sheets": "xlsx xls csv tsv numbers ods",
    "docs": "docx doc md txt rtf pages odt pptx ppt key",
    "web": "html htm mhtml",
    "archives": "zip rar 7z tar gz tgz bz2 xz",
    "installers": "dmg pkg exe msi deb appimage",
    "code-data": "py js ts json yaml yml sh xml sql",
    "audio": "mp3 m4a wav aac flac ogg opus",
}
EXT = {e: k for k, v in TYPES.items() for e in v.split()}
SCREENSHOT = re.compile(r"(screen ?shot|screenshot|截屏|屏幕截图|截图|Screen Recording|屏幕录制)", re.I)
CHAT = re.compile(r"(WhatsApp (Image|Video)|Weixin (Image|Video)|微信图片|微信视频|IMG-\d{8}-WA|VID-\d{8}-WA|telegram|signal-)", re.I)
DATE_IN_NAME = re.compile(r"(20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?([0-2]\d|3[01])")
RECENT_SEC = 600


def X(p):
    return os.path.abspath(os.path.expanduser(p))


def ext(n):
    return n.rsplit(".", 1)[-1].lower() if "." in n else ""


def skippable(p):
    n = os.path.basename(p)
    if n.startswith(".") or n in ("Icon\r", "desktop.ini", "Thumbs.db") or os.path.islink(p):
        return True
    if os.path.isdir(p) and (os.path.exists(os.path.join(p, ".git")) or n.endswith((".photoslibrary", ".app", ".bundle"))):
        return True
    try:
        return os.path.isfile(p) and time.time() - os.path.getmtime(p) < RECENT_SEC
    except OSError:
        return True


def capture_date(p):
    """Best effort, no third-party deps: macOS Spotlight -> ffprobe (video) -> date in filename -> mtime."""
    if sys.platform == "darwin":
        try:
            o = subprocess.run(["mdls", "-raw", "-nullMarker", "", "-name", "kMDItemContentCreationDate",
                                "-name", "kMDItemFSCreationDate", p], capture_output=True, text=True, timeout=10).stdout
            content, fs = (o.split("\0") + ["", ""])[:2]
            if content and content != fs:  # equal = Spotlight only copied the filesystem date, no EXIF/QuickTime date
                return dt.datetime.strptime(content[:19], "%Y-%m-%d %H:%M:%S"), "metadata"
        except Exception:
            pass
    if EXT.get(ext(p)) == "videos":
        try:
            o = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format_tags=creation_time",
                                "-of", "default=nw=1:nk=1", p], capture_output=True, text=True, timeout=20).stdout.strip()
            if o:
                return dt.datetime.strptime(o[:19], "%Y-%m-%dT%H:%M:%S"), "metadata"
        except Exception:
            pass
    m = DATE_IN_NAME.search(os.path.basename(p))
    if m:
        try:
            return dt.datetime(int(m[1]), int(m[2]), int(m[3])), "filename"
        except ValueError:
            pass
    return dt.datetime.fromtimestamp(os.path.getmtime(p)), "mtime"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def plan_rules(t, labels):
    root, out, unmatched = X(t["path"]), [], []
    cats = {r["to"] for r in t["rules"]} | set(labels.values()) | set(t.get("keep_dirs", []))
    for n in sorted(os.listdir(root)):
        p = os.path.join(root, n)
        if n in cats or skippable(p) or any(re.search(k, n) for k in t.get("keep", [])):
            continue
        to = labels.get(n) or next((r["to"] for r in t["rules"] if re.search(r["match"], n, re.I)), None)
        if to:
            out.append((p, os.path.join(root, to), "label" if n in labels else "rule"))
        else:
            unmatched.append(p)
    return out, unmatched


def plan_inbox(t, labels):
    root, out = X(t["path"]), []
    cut = time.time() - t.get("keep_days", 30) * 86400
    arch = os.path.join(root, t.get("archive", "Archive"))
    names = {**{k: k for k in TYPES}, **t.get("type_names", {})}
    for n in sorted(os.listdir(root)):
        p = os.path.join(root, n)
        if not os.path.isfile(p) or skippable(p) or os.path.getmtime(p) > cut:
            continue
        out.append((p, os.path.join(arch, names.get(EXT.get(ext(n), "other"), names.get("other", "other"))), "age"))
    return out, []


def plan_media(t, labels):
    src, dest = X(t["path"]), X(t["dest"])
    k = {"photos": "photos", "videos": "videos", "screenshots": "screenshots", "chat": "chat",
         "duplicates": "_duplicates", **t.get("kind_names", {})}
    out, seen, sources = [], {}, {"metadata": 0, "filename": 0, "mtime": 0}
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in sorted(dirs) if not skippable(os.path.join(d, x)) and not X(os.path.join(d, x)).startswith(dest)]
        for n in sorted(files):
            p = os.path.join(d, n)
            kind = EXT.get(ext(n))
            if kind not in ("images", "videos") or skippable(p):
                continue
            h = sha(p)
            if h in seen:
                out.append((p, os.path.join(dest, k["duplicates"]), "dup of " + os.path.basename(seen[h])))
                continue
            seen[h] = p
            when, how = capture_date(p)
            sources[how] += 1
            lab = labels.get(n) or labels.get(p)
            kk = lab or (k["screenshots"] if SCREENSHOT.search(n) else k["chat"] if CHAT.search(n)
                         else k["photos"] if kind == "images" else k["videos"])
            sub = t.get("layout", "{kind}/{yyyy}/{yyyy}-{mm}").format(kind=kk, yyyy=when.year, mm=f"{when.month:02d}")
            out.append((p, os.path.join(dest, sub), how))
    print(f"date source: {sources}  (mtime = least reliable)")
    return out, []


def free(dst_dir, name, taken):
    stem, dot, e = name.rpartition(".") if "." in name else (name, "", "")
    i, cand = 1, name
    while os.path.exists(os.path.join(dst_dir, cand)) or os.path.join(dst_dir, cand) in taken:
        i += 1
        cand = f"{stem} ({i}){dot}{e}" if dot else f"{name} ({i})"
    return os.path.join(dst_dir, cand)


def sheets(files, out, per):
    """Contact sheets (5 x per/5 grid, 240px cells) so a human or a vision model can classify many files at once.
    Needs ffmpeg; on macOS uses sips for HEIC. Writes sheet-NNN.jpg + sheet-NNN.txt (cell number -> path)."""
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "_thumbs")
    os.makedirs(tmp, exist_ok=True)
    made = []
    for i in range(0, len(files), per):
        batch, cells = files[i:i + per], []
        for j, f in enumerate(batch):
            th = os.path.join(tmp, f"{i + j:05d}.jpg")
            src = f
            if EXT.get(ext(f)) == "images" and sys.platform == "darwin":  # sips reads HEIC even when misnamed .JPG
                subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "480", f, "--out", th], capture_output=True)
                if os.path.exists(th):
                    src = th
            cmd = ["ffmpeg", "-y", "-v", "quiet"] + (["-ss", "1"] if EXT.get(ext(f)) == "videos" else []) + ["-i", src,
                   "-frames:v", "1", "-vf", "scale=240:240:force_original_aspect_ratio=decrease,pad=240:240:(ow-iw)/2:(oh-ih)/2", th]
            subprocess.run(cmd, capture_output=True)
            if not os.path.exists(th) and EXT.get(ext(f)) == "videos":  # clips shorter than 1s
                subprocess.run([c for c in cmd if c not in ("-ss", "1")], capture_output=True)
            cells.append(th if os.path.exists(th) else None)
        black = os.path.join(tmp, "black.jpg")
        if not os.path.exists(black):
            subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-f", "lavfi", "-i", "color=black:s=240x240", "-frames:v", "1", black])
        rows = (len(batch) + 4) // 5
        grid = [c or black for c in cells] + [black] * (rows * 5 - len(cells))  # unreadable files stay black in place
        name = os.path.join(out, f"sheet-{i // per + 1:03d}")
        inputs = sum((["-i", c] for c in grid), [])
        lay = "|".join(f"{(k % 5) * 240}_{(k // 5) * 240}" for k in range(len(grid)))
        fl = "".join(f"[{k}:v]" for k in range(len(grid))) + f"xstack=inputs={len(grid)}:layout={lay}[o]"
        subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fl, "-map", "[o]", "-frames:v", "1", name + ".jpg"])
        with open(name + ".txt", "w") as t:
            for j, f in enumerate(batch):
                t.write(f"{j + 1:3}  row {j // 5 + 1} col {j % 5 + 1}  {f}\n")
        made.append(name + ".jpg")
    return made


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("cmd", choices=["plan", "apply", "refs", "sheet"])
    a.add_argument("--config", default="~/.config/file-tidy/config.json")
    a.add_argument("--target", help="target name from the config (plan)")
    a.add_argument("--labels", help="JSON {filename_or_path: category} decided by a human/AI for unmatched items")
    a.add_argument("--plan-file", help="plan JSON to apply / check refs for / make sheets from")
    a.add_argument("--dir", help="sheet: folder of photos/videos to put on contact sheets")
    a.add_argument("--per", type=int, default=20, help="sheet: thumbnails per sheet (grid 5 wide)")
    o = a.parse_args()
    cfg = json.load(open(X(o.config)))
    state = X(cfg.get("state_dir", "~/.local/state/file-tidy"))
    os.makedirs(state, exist_ok=True)

    if o.cmd == "plan":
        t = next((t for t in cfg["targets"] if t["name"] == o.target), None)
        if not t:
            sys.exit(f"no target {o.target!r}; have: {[t['name'] for t in cfg['targets']]}")
        labels = json.load(open(X(o.labels))) if o.labels else {}
        moves, unmatched = {"rules": plan_rules, "inbox": plan_inbox, "media": plan_media}[t["mode"]](t, labels)
        taken, rows = set(), []
        for s, dd, why in moves:
            d = free(dd, os.path.basename(s), taken)
            taken.add(d)
            rows.append({"src": s, "dst": d, "why": why})
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        pf = os.path.join(state, f"plan-{t['name']}-{stamp}.json")
        json.dump({"target": t["name"], "moves": rows, "unmatched": unmatched}, open(pf, "w"), ensure_ascii=False, indent=1)
        cnt = {}
        for r in rows:
            k = os.path.relpath(os.path.dirname(r["dst"]), X(t.get("dest", t["path"])))
            cnt[k] = cnt.get(k, 0) + 1
        for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
            print(f"{v:6}  {k}")
        print(f"moves: {len(rows)}  unmatched: {len(unmatched)}")
        for u in unmatched:
            print("  UNMATCHED", u)
        print("plan:", pf)

    elif o.cmd == "apply":
        p = json.load(open(X(o.plan_file)))
        undo = X(o.plan_file).replace("plan-", "undo-").replace(".json", ".sh")
        done = 0
        with open(undo, "w") as u:
            u.write("#!/bin/sh\n# undo for " + o.plan_file + "\n")
            for r in p["moves"]:
                if not os.path.exists(r["src"]) or os.path.exists(r["dst"]):
                    print("SKIP", r["src"])
                    continue
                os.makedirs(os.path.dirname(r["dst"]), exist_ok=True)
                os.rename(r["src"], r["dst"])
                u.write(f"mkdir -p {shlex.quote(os.path.dirname(r['src']))} && mv -n {shlex.quote(r['dst'])} {shlex.quote(r['src'])}\n")
                done += 1
        print(f"moved {done}/{len(p['moves'])}\nundo: sh {undo}")

    elif o.cmd == "sheet":
        if o.plan_file:
            files = [r["src"] for r in json.load(open(X(o.plan_file)))["moves"] if not r["why"].startswith("dup")]
        else:
            files = sorted(os.path.join(d, n) for d, _, fs in os.walk(X(o.dir)) for n in fs if EXT.get(ext(n)) in ("images", "videos"))
        files = [f for f in files if EXT.get(ext(f)) in ("images", "videos")]
        out = os.path.join(state, "sheets-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
        for m in sheets(files, out, o.per):
            print(m)
        print(f"{len(files)} files; cell index in the .txt next to each sheet")

    elif o.cmd == "refs":
        p = json.load(open(X(o.plan_file)))
        home = os.path.expanduser("~")
        olds = {}
        for r in p["moves"]:
            for form in (r["src"], r["src"].replace(home, "~", 1), r["src"].replace(home + "/", "", 1)):
                olds[form] = r["dst"]
        hits = 0
        for root in cfg.get("refs_roots", []):
            for d, dirs, files in os.walk(X(root)):
                dirs[:] = [x for x in dirs if not x.startswith(".")]
                for n in files:
                    if ext(n) not in ("md", "txt", "json", "sh", "py", "yaml", "yml", "html"):
                        continue
                    f = os.path.join(d, n)
                    try:
                        if os.path.getsize(f) > 2_000_000:
                            continue
                        s = open(f, encoding="utf-8", errors="ignore").read()
                    except OSError:
                        continue
                    for old, new in olds.items():
                        if old in s:
                            hits += 1
                            print(f"{f}\n    {old}\n -> {new}")
        print(f"stale references: {hits}")


if __name__ == "__main__":
    main()
