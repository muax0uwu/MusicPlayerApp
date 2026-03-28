# SimpMusic — Railway Deployment

A Django music player that acts as a third-party client for YouTube Music.

---

## Why Stream Error Happens on Railway (and How It's Fixed)

YouTube blocks stream URL requests from cloud/datacenter IPs (AWS, GCP, Railway)
when using yt-dlp's default `web` player client. Works locally because your home
IP isn't on YouTube's blocklist.

**Fix applied:**
1. yt-dlp now uses the `android_music` player client — far less blocked on cloud IPs
2. The resolved CDN URLs are **not IP-bound**, so the browser can fetch them directly
3. Django sends a `302 redirect` to that CDN URL instead of proxying the stream
4. Only Range requests (seeking) fall back to server-side proxying

---

## Deploy to Railway

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "SimpMusic Railway"
git remote add origin https://github.com/YOU/simpmusic.git
git push -u origin main
```

### 2. Create Railway project
- Go to railway.app → New Project → Deploy from GitHub repo
- Select your repo

### 3. Set environment variables in Railway dashboard
| Variable | Value |
|---|---|
| `SECRET_KEY` | any long random string |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `your-app.up.railway.app` |

### 4. Railway auto-detects `nixpacks.toml` and deploys

---

## Local Development
```bash
pip install -r requirements.txt
python manage.py runserver
```

## Debug endpoint
Visit `/api/debug/` on your deployed URL to check package versions and test
yt-dlp stream resolution from Railway's servers.

---

## Architecture

```
Browser → Django (/api/proxy/:id/)
              ↓
          yt-dlp android_music client
              ↓
         YouTube CDN URL (not IP-locked)
              ↓
         302 Redirect → Browser fetches audio directly from CDN
```

## Gunicorn config (Procfile)
- `--timeout 120` : yt-dlp resolution takes 5-20s, default 30s kills it
- `--workers 2 --threads 4` : handles concurrent streams + API calls
- `--worker-class gthread` : thread-based, better for I/O-bound work
