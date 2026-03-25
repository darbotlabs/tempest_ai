"""
game_catalog.py — Anton Game Catalog Module

Parses the MAME HyperList XML database and cross-references ROMs, wheel art,
and preview videos to build a unified game catalog for the tempest_ai project.
"""

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class GameEntry:
    game_id: str            # MAME ROM name
    description: str        # Human-readable title
    manufacturer: str
    year: str
    genre: str
    clone_of: str           # Empty = parent
    is_parent: bool
    has_rom: bool
    has_wheel_art: bool
    has_video: bool
    wheel_art_path: str     # Relative to PROJECT_ROOT
    video_path: str         # Relative to PROJECT_ROOT


class GameCatalog:
    """Loads and indexes the full MAME arcade library."""

    def __init__(self, project_root: str):
        self._project_root = os.path.abspath(project_root)
        self._games: dict[str, GameEntry] = {}
        self._genres: list[str] = []
        self._games_by_genre: dict[str, list[str]] = {}

        self._rom_set: set[str] = set()
        self._wheel_set: set[str] = set()
        self._video_map: dict[str, str] = {}   # game_id → relative path

        self._index_assets()
        self._parse_genres()
        self._parse_games()

    # ------------------------------------------------------------------
    # Asset indexing (fast: just list directories once)
    # ------------------------------------------------------------------

    def _index_assets(self) -> None:
        # ROMs
        rom_dir = os.path.join(self._project_root, "MAME_ROMS")
        if os.path.isdir(rom_dir):
            for f in os.listdir(rom_dir):
                if f.lower().endswith(".zip"):
                    self._rom_set.add(f[:-4])

        # Wheel art
        wheel_dir = os.path.join(self._project_root,
                                 "MAME_FRONTEND", "MAME", "Images", "Wheel")
        if os.path.isdir(wheel_dir):
            for f in os.listdir(wheel_dir):
                if f.lower().endswith(".png"):
                    self._wheel_set.add(f[:-4])

        # Videos — root level and letter subdirs
        video_base = os.path.join(self._project_root,
                                  "MAME_FRONTEND", "MAME", "Video")
        if os.path.isdir(video_base):
            # Root-level .flv files
            for f in os.listdir(video_base):
                full = os.path.join(video_base, f)
                if os.path.isfile(full) and f.lower().endswith(".flv"):
                    gid = f[:-4]
                    self._video_map[gid] = os.path.join(
                        "MAME_FRONTEND", "MAME", "Video", f)

            # Letter subdirectories
            for subdir in os.listdir(video_base):
                sub_path = os.path.join(video_base, subdir)
                if not os.path.isdir(sub_path):
                    continue
                if subdir == "Override Transitions":
                    continue
                for f in os.listdir(sub_path):
                    if f.lower().endswith(".flv"):
                        gid = f[:-4]
                        # Prefer subdir path (more organized) over root
                        self._video_map[gid] = os.path.join(
                            "MAME_FRONTEND", "MAME", "Video", subdir, f)

    # ------------------------------------------------------------------
    # Genre list from Genre.xml
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_xml(text: str) -> str:
        """Fix unescaped ampersands that are not valid XML entities."""
        return re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#)', '&amp;', text)

    def _parse_genres(self) -> None:
        genre_path = os.path.join(self._project_root,
                                  "MAME_DATABASE", "Genre.xml")
        if not os.path.isfile(genre_path):
            return
        with open(genre_path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        root = ET.fromstring(self._sanitize_xml(raw))
        all_games_entry: Optional[str] = None
        others: list[str] = []
        for game_el in root.findall("game"):
            name = game_el.get("name", "").strip()
            if not name:
                continue
            if name == "All Games":
                all_games_entry = name
            else:
                others.append(name)
        others.sort()
        if all_games_entry:
            self._genres = [all_games_entry] + others
        else:
            self._genres = others

    # ------------------------------------------------------------------
    # Main game database from MAME.xml
    # ------------------------------------------------------------------

    def _parse_games(self) -> None:
        mame_path = os.path.join(self._project_root,
                                 "MAME_DATABASE", "MAME.xml")
        if not os.path.isfile(mame_path):
            return

        with open(mame_path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        root = ET.fromstring(self._sanitize_xml(raw))

        for game_el in root.findall("game"):
            gid = game_el.get("name", "").strip()
            if not gid:
                continue

            clone_of = (game_el.findtext("cloneof") or "").strip()
            is_parent = (clone_of == "")
            genre = (game_el.findtext("genre") or "").strip()

            has_rom = gid in self._rom_set
            has_wheel = gid in self._wheel_set
            has_video = gid in self._video_map

            wheel_path = ""
            if has_wheel:
                wheel_path = os.path.join(
                    "MAME_FRONTEND", "MAME", "Images", "Wheel",
                    f"{gid}.png")

            video_path = self._video_map.get(gid, "")

            entry = GameEntry(
                game_id=gid,
                description=(game_el.findtext("description") or "").strip(),
                manufacturer=(game_el.findtext("manufacturer") or "").strip(),
                year=(game_el.findtext("year") or "").strip(),
                genre=genre,
                clone_of=clone_of,
                is_parent=is_parent,
                has_rom=has_rom,
                has_wheel_art=has_wheel,
                has_video=has_video,
                wheel_art_path=wheel_path,
                video_path=video_path,
            )
            self._games[gid] = entry

            # Index by genre
            if genre:
                self._games_by_genre.setdefault(genre, []).append(gid)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def games(self) -> dict[str, GameEntry]:
        """All games keyed by game_id."""
        return self._games

    @property
    def genres(self) -> list[str]:
        """Ordered genre list from Genre.xml."""
        return self._genres

    @property
    def games_by_genre(self) -> dict[str, list[str]]:
        """Genre name → list of game_ids."""
        return self._games_by_genre

    def search(self, query: str, parents_only: bool = True,
               launchable_only: bool = True) -> list[GameEntry]:
        """Case-insensitive substring search across description, manufacturer, game_id."""
        q = query.lower()
        results: list[GameEntry] = []
        for g in self._games.values():
            if parents_only and not g.is_parent:
                continue
            if launchable_only and not g.has_rom:
                continue
            if (q in g.description.lower()
                    or q in g.manufacturer.lower()
                    or q in g.game_id.lower()):
                results.append(g)
        results.sort(key=lambda g: g.description.lower())
        return results

    def get_genre(self, genre: str, parents_only: bool = True,
                  launchable_only: bool = True) -> list[GameEntry]:
        """Get games in a genre, sorted by description."""
        ids = self._games_by_genre.get(genre, [])
        results: list[GameEntry] = []
        for gid in ids:
            g = self._games[gid]
            if parents_only and not g.is_parent:
                continue
            if launchable_only and not g.has_rom:
                continue
            results.append(g)
        results.sort(key=lambda g: g.description.lower())
        return results

    def get_launchable(self, parents_only: bool = True) -> list[GameEntry]:
        """All games with has_rom=True."""
        results: list[GameEntry] = []
        for g in self._games.values():
            if not g.has_rom:
                continue
            if parents_only and not g.is_parent:
                continue
            results.append(g)
        results.sort(key=lambda g: g.description.lower())
        return results

    def get_parents(self) -> list[GameEntry]:
        """All parent games."""
        results = [g for g in self._games.values() if g.is_parent]
        results.sort(key=lambda g: g.description.lower())
        return results

    def is_launchable(self, game_id: str) -> bool:
        """Quick check: does this game_id have a ROM?"""
        g = self._games.get(game_id)
        return g is not None and g.has_rom

    def genre_summary(self) -> list[dict]:
        """Return [{name, total, launchable, fully_ready}, ...] for UI."""
        summary: list[dict] = []
        for genre in sorted(self._games_by_genre.keys()):
            ids = self._games_by_genre[genre]
            total = len(ids)
            launchable = sum(1 for gid in ids
                             if self._games[gid].has_rom)
            fully_ready = sum(
                1 for gid in ids
                if (self._games[gid].has_rom
                    and self._games[gid].has_wheel_art
                    and self._games[gid].has_video))
            summary.append({
                "name": genre,
                "total": total,
                "launchable": launchable,
                "fully_ready": fully_ready,
            })
        return summary

    def to_json_entry(self, game: GameEntry) -> dict:
        """Convert to JSON-serializable dict for API responses."""
        return asdict(game)

    def to_json_list(self, games: list[GameEntry]) -> list[dict]:
        """Batch convert for API responses."""
        return [asdict(g) for g in games]


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_catalog: GameCatalog | None = None


def get_catalog() -> GameCatalog:
    """Return the shared GameCatalog instance, creating it on first call."""
    global _catalog
    if _catalog is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _catalog = GameCatalog(project_root)
    return _catalog


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import time

    t0 = time.perf_counter()
    catalog = get_catalog()
    elapsed = time.perf_counter() - t0

    total = len(catalog.games)
    parents = sum(1 for g in catalog.games.values() if g.is_parent)
    clones = total - parents
    with_rom = sum(1 for g in catalog.games.values() if g.has_rom)
    with_wheel = sum(1 for g in catalog.games.values() if g.has_wheel_art)
    with_video = sum(1 for g in catalog.games.values() if g.has_video)
    fully_ready = sum(
        1 for g in catalog.games.values()
        if g.has_rom and g.has_wheel_art and g.has_video)
    launchable_parents = len(catalog.get_launchable(parents_only=True))

    print("=" * 55)
    print("  Anton Game Catalog — Summary")
    print("=" * 55)
    print(f"  Loaded in           {elapsed:.3f}s")
    print(f"  Total games         {total:>6,}  ({parents:,} parents, {clones:,} clones)")
    print(f"  With ROM            {with_rom:>6,}")
    print(f"  With wheel art      {with_wheel:>6,}")
    print(f"  With video          {with_video:>6,}")
    print(f"  Fully ready         {fully_ready:>6,}  (ROM + art + video)")
    print(f"  Launchable parents  {launchable_parents:>6,}")
    print(f"  Genres (Genre.xml)  {len(catalog.genres):>6}")
    print(f"  Genres (in-game)    {len(catalog.games_by_genre):>6}")
    print("-" * 55)

    # Top 5 genres by launchable count
    gs = catalog.genre_summary()
    gs.sort(key=lambda x: x["launchable"], reverse=True)
    print("  Top genres by launchable games:")
    for entry in gs[:5]:
        print(f"    {entry['name']:<30s} "
              f"{entry['launchable']:>4} / {entry['total']:>4}")
    print("=" * 55)
