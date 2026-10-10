"""Directory tree model used by the curses navigator."""
from pathlib import Path
import os


class Tree:
    def __init__(self, root):
        self.root = Path(root)
        self.expanded = set()
        self.hidden = False
        self.message = ''

    def rows(self):
        rows = []
        def visit(path, depth, ancestors, directory):
            rows.append((path, depth, directory))
            if not directory or path not in self.expanded:
                return
            try:
                real = path.resolve()
                if real in ancestors:
                    self.message = 'Symlink cycle: cannot expand this directory.'
                    return
                with os.scandir(path) as entries:
                    children = [(Path(entry.path), entry.is_dir()) for entry in entries
                                if self.hidden or not entry.name.startswith('.')]
                children.sort(key=lambda child: (not child[1], child[0].name.casefold()))
                descendants = ancestors | {real}
                for child, is_directory in children:
                    visit(child, depth + 1, descendants, is_directory)
            except OSError as error:
                self.message = str(error)
        visit(self.root, 0, set(), self.root.is_dir())
        return rows

