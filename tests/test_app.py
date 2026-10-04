import tempfile
import unittest
from pathlib import Path

from safesort.app import HISTORY_NAME, apply_moves, category_for, main, plan_moves, undo_last


class SafeSortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_classifies_extensions_case_insensitively(self):
        self.assertEqual(category_for(Path("photo.JPEG")), "Images")
        self.assertEqual(category_for(Path("notes.md")), "Documents")
        self.assertEqual(category_for(Path("archive.unknown")), "Other")
        self.assertEqual(category_for(Path("LICENSE")), "No Extension")

    def test_preview_does_not_move_files(self):
        file = self.root / "photo.jpg"
        file.write_bytes(b"image")
        moves = plan_moves(self.root)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].destination.relative_to(self.root).as_posix(), "Images/photo.jpg")
        self.assertTrue(file.exists())
        self.assertEqual(main([str(self.root)]), 0)
        self.assertTrue(file.exists())

    def test_apply_resolves_collision_and_undo_restores_both(self):
        (self.root / "photo.png").write_bytes(b"one")
        (self.root / "Images").mkdir()
        (self.root / "Images" / "photo.png").write_bytes(b"existing")
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "photo.png").write_bytes(b"two")
        moves = plan_moves(self.root, recursive=True)
        planned = {m.destination.name for m in moves}
        self.assertIn("photo (1).png", planned)
        self.assertIn("photo (2).png", planned)
        batch = apply_moves(self.root, moves)
        self.assertTrue(batch)
        self.assertTrue((self.root / HISTORY_NAME).exists())
        self.assertEqual(undo_last(self.root), 2)
        self.assertEqual((self.root / "photo.png").read_bytes(), b"one")
        self.assertEqual((nested / "photo.png").read_bytes(), b"two")
        self.assertEqual((self.root / "Images" / "photo.png").read_bytes(), b"existing")
        with self.assertRaisesRegex(ValueError, "no unapplied"):
            undo_last(self.root)

    def test_cli_apply_then_undo(self):
        (self.root / "report.pdf").write_text("report")
        self.assertEqual(main([str(self.root), "--apply"]), 0)
        self.assertTrue((self.root / "Documents" / "report.pdf").exists())
        self.assertEqual(main([str(self.root), "--undo"]), 0)
        self.assertTrue((self.root / "report.pdf").exists())

    def test_recursive_scan_skips_development_metadata(self):
        (self.root / ".git" / "objects").mkdir(parents=True)
        (self.root / ".git" / "objects" / "pack.zip").write_bytes(b"git data")
        (self.root / "node_modules" / "pkg").mkdir(parents=True)
        (self.root / "node_modules" / "pkg" / "package.json").write_text("{}")
        (self.root / "project" ).mkdir()
        (self.root / "project" / "guide.pdf").write_bytes(b"guide")
        moves = plan_moves(self.root, recursive=True)
        self.assertEqual([move.source.name for move in moves], ["guide.pdf"])

    def test_missing_directory_rejected(self):
        self.assertEqual(main([str(self.root / "missing")]), 2)


if __name__ == "__main__":
    unittest.main()
