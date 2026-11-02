import json, os, subprocess, sys, tempfile, time, unittest

TIDY = os.path.join(os.path.dirname(__file__), "..", "skills", "file-tidy", "scripts", "tidy.py")
OLD = time.time() - 90 * 86400


def touch(p, data=b"x", old=True):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    if old:
        os.utime(p, (OLD, OLD))


class Tidy(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        j = lambda *a: os.path.join(self.t, *a)
        self.j = j
        # rules target
        touch(j("desk", "2026A001_Acme_invoice.pdf"))
        touch(j("desk", "passport.pdf"))
        touch(j("desk", "mystery.bin"))
        touch(j("desk", "launcher.command"))
        touch(j("desk", "repo", ".git", "HEAD"))
        touch(j("desk", "fresh_invoice.pdf"), old=False)
        # inbox target
        touch(j("dl", "old.zip"))
        touch(j("dl", "old.pdf"))
        touch(j("dl", "new.pdf"), old=False)
        touch(j("dl", "folder", "inside.pdf"))
        # media target
        touch(j("media", "IMG_1.JPG"), b"photo-a")
        touch(j("media", "sub", "IMG_1 copy.JPG"), b"photo-a")
        touch(j("media", "IMG_2 copy.JPG"), b"photo-b")
        touch(j("media", "IMG_2.JPG"), b"photo-b")
        touch(j("media", "Screenshot 2025-03-04 at 10.00.00.png"), b"shot")
        touch(j("media", "WhatsApp Image 2024-12-01 at 09.00.jpg"), b"chat")
        touch(j("media", "clip.mov"), b"video")
        touch(j("media", "notes.txt"), b"not media")
        self.cfg = j("config.json")
        json.dump({"state_dir": j("state"), "refs_roots": [j("notes")], "targets": [
            {"name": "desk", "mode": "rules", "path": j("desk"), "keep": [r"\.command$"],
             "rules": [{"match": "invoice", "to": "Invoices"}, {"match": "passport", "to": "Personal"}]},
            {"name": "dl", "mode": "inbox", "path": j("dl"), "keep_days": 30, "archive": "Archive"},
            {"name": "media", "mode": "media", "path": j("media"), "dest": j("sorted")},
        ]}, open(self.cfg, "w"))
        touch(j("notes", "a.md"), ("see " + j("desk", "passport.pdf")).encode())

    def run_cmd(self, *a):
        r = subprocess.run([sys.executable, TIDY, *a, "--config", self.cfg], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def plan(self, name, *extra):
        out = self.run_cmd("plan", "--target", name, *extra)
        return out, out.strip().splitlines()[-1].split("plan: ")[1]

    def test_rules_apply_undo_refs(self):
        out, pf = self.plan("desk")
        self.assertIn("UNMATCHED", out)
        self.assertIn("mystery.bin", out)
        lab = self.j("labels.json")
        json.dump({"mystery.bin": "Misc"}, open(lab, "w"))
        out, pf = self.plan("desk", "--labels", lab)
        self.assertIn("unmatched: 0", out)
        refs = self.run_cmd("refs", "--plan-file", pf)
        self.assertIn("stale references: 1", refs)
        self.run_cmd("apply", "--plan-file", pf)
        self.assertTrue(os.path.exists(self.j("desk", "Invoices", "2026A001_Acme_invoice.pdf")))
        self.assertTrue(os.path.exists(self.j("desk", "Misc", "mystery.bin")))
        for keep in ("launcher.command", "repo", "fresh_invoice.pdf"):  # keep rule, git repo, recently modified
            self.assertTrue(os.path.exists(self.j("desk", keep)), keep)
        subprocess.run(["sh", pf.replace("plan-", "undo-").replace(".json", ".sh")], check=True)
        self.assertTrue(os.path.exists(self.j("desk", "passport.pdf")))

    def test_inbox(self):
        _, pf = self.plan("dl")
        self.run_cmd("apply", "--plan-file", pf)
        self.assertTrue(os.path.exists(self.j("dl", "Archive", "archives", "old.zip")))
        self.assertTrue(os.path.exists(self.j("dl", "Archive", "pdf", "old.pdf")))
        self.assertTrue(os.path.exists(self.j("dl", "new.pdf")))
        self.assertTrue(os.path.exists(self.j("dl", "folder", "inside.pdf")))

    def test_media(self):
        _, pf = self.plan("media")
        self.run_cmd("apply", "--plan-file", pf)
        got = sorted(os.path.relpath(os.path.join(d, f), self.j("sorted")) for d, _, fs in os.walk(self.j("sorted")) for f in fs)
        self.assertIn("screenshots/2025/2025-03/Screenshot 2025-03-04 at 10.00.00.png", got)
        self.assertIn("chat/2024/2024-12/WhatsApp Image 2024-12-01 at 09.00.jpg", got)
        self.assertEqual(sorted(g for g in got if g.startswith("_duplicates/")),
                         ["_duplicates/IMG_1 copy.JPG", "_duplicates/IMG_2 copy.JPG"])
        self.assertEqual(sum(g.startswith("photos/") for g in got), 2)
        self.assertEqual(sum(g.startswith("videos/") for g in got), 1)
        self.assertTrue(os.path.exists(self.j("media", "notes.txt")))


if __name__ == "__main__":
    unittest.main()
