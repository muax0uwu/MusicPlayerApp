# SimpMusic 🎵

A modern Django music player that acts as a specialized third-party client for YouTube Music.
It parses YouTube's publicly available APIs and streams audio — the same way a browser with
an ad-blocker would — but with a beautiful custom UI.

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

This installs:
- **Django** — web framework
- **yt-dlp** — resolves audio stream URLs from YouTube
- **ytmusicapi** — queries YouTube Music for search, charts, albums, artists, lyrics

### 2. Run the server

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000` in your browser.

---

## Features

| Feature | How it works |
|---|---|
| 🔍 Search | Queries YouTube Music API via `ytmusicapi` |
| 🎵 Audio playback | `yt-dlp` extracts the best audio-only stream URL |
| 🔄 Auto-queue | Loads related tracks when queue runs out |
| 📖 Lyrics | Fetches lyrics from YouTube Music |
| 💿 Album / Artist pages | Full album track lists and artist discographies |
| 🔀 Shuffle / Repeat | Client-side queue management |
| ⌨️ Keyboard shortcuts | `Space` play/pause, `←→` seek ±10s, `Esc` close panel |
| 📡 Proxy streaming | Audio proxied through Django to avoid CORS issues |

---

## Architecture

```
Browser ──→ Django (SimpMusic)
                ├── /api/search/        ← ytmusicapi
                ├── /api/home/          ← ytmusicapi charts
                ├── /api/track/:id/     ← ytmusicapi song info
                ├── /api/track/:id/lyrics/   ← ytmusicapi
                ├── /api/track/:id/related/  ← ytmusicapi watch playlist
                ├── /api/stream/:id/    ← yt-dlp (resolves URL, no proxy)
                ├── /api/proxy/:id/     ← yt-dlp + Django streaming proxy
                ├── /api/album/:id/     ← ytmusicapi
                └── /api/artist/:id/   ← ytmusicapi
```

### Why this is legal / ethical

SimpMusic acts strictly as a specialized third-party web browser / client.
It parses publicly available YouTube and YouTube Music content — identical to
what any browser with uBlock Origin would do. No content is stored or redistributed.

---

## Project Structure

```
simpmusic/
├── manage.py
├── requirements.txt
├── simpmusic/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── player/
    ├── views.py      ← all API logic
    ├── urls.py
    └── templates/
        └── player/
            └── index.html   ← complete SPA frontend
```

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Space` | Play / Pause |
| `→` | Seek +10s |
| `←` | Seek −10s |
| `Esc` | Close now-playing panel |

---

## Notes

- Stream URLs from YouTube expire after ~6 hours; SimpMusic caches them for 4.5 minutes.
- For production use, set `SECRET_KEY` in settings and `DEBUG = False`.
- No database is required — SimpMusic has no models.
