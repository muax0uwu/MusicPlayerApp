"""
SimpMusic Player Views — Railway Edition

Key fix: YouTube blocks cloud/datacenter IPs with the default 'web' yt-dlp client.
Solution: use android_music / ios clients which:
  1. Are far less aggressively blocked on cloud IPs
  2. Return CDN URLs that are NOT tied to the requesting IP
  3. Allow a simple HTTP redirect instead of proxying (no timeout risk)
"""
import traceback
import threading
import logging
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse, HttpResponseRedirect
from django.views.decorators.http import require_GET
from django.shortcuts import render

logger = logging.getLogger(__name__)

_stream_cache: dict = {}   # { video_id: (url, expires_at) }
_cache_lock = threading.Lock()

# yt-dlp options tuned for cloud/Railway deployment
# android_music client bypasses datacenter IP blocks and returns IP-independent URLs
_YDL_OPTS = {
    'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'nocheckcertificate': True,
    'extractor_args': {
        'youtube': {
            # android_music → not IP-locked, works from Railway/cloud
            # falls back to ios, then web if needed
            'player_client': ['android_music', 'ios', 'web'],
            'skip': ['hls', 'dash'],  # get direct http urls, not adaptive manifests
        }
    },
    'http_headers': {
        'User-Agent': (
            'com.google.android.apps.youtube.music/'
            '5.34.51 (Linux; U; Android 11) gzip'
        ),
        'Accept-Language': 'en-US,en;q=0.9',
    },
}


def index(request):
    return render(request, 'player/index.html')


# ── Debug ─────────────────────────────────────────────────────────────────────

@require_GET
def debug(request):
    import sys
    result = {'python': sys.version, 'packages': {}}
    for pkg in ('ytmusicapi', 'yt_dlp', 'requests'):
        try:
            mod = __import__(pkg)
            v = getattr(mod, '__version__', None) or getattr(getattr(mod, 'version', None), '__version__', 'ok')
            result['packages'][pkg] = str(v)
        except Exception as e:
            result['packages'][pkg] = f'MISSING: {e}'
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        sr = yt.search('Coldplay', filter='songs', limit=2)
        result['search_test'] = f'OK — {len(sr)} results'
    except Exception as e:
        result['search_test'] = f'FAILED: {e}\n{traceback.format_exc()}'
    return JsonResponse(result)


# ── Search ────────────────────────────────────────────────────────────────────

@require_GET
def search(request):
    query = request.GET.get('q', '').strip()
    search_type = request.GET.get('type', 'songs')
    if not query:
        return JsonResponse({'error': 'Missing query'}, status=400)
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        results = yt.search(query, filter=search_type, limit=20)
        return JsonResponse({'results': _normalize_results(results, search_type)})
    except Exception as e:
        logger.exception('search failed')
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def search_suggestions(request):
    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'suggestions': []})
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        raw = yt.get_search_suggestions(query)
        suggestions = []
        for item in raw[:8]:
            if isinstance(item, str):
                suggestions.append(item)
            elif isinstance(item, dict):
                suggestions.append(item.get('suggestion') or item.get('query') or '')
        return JsonResponse({'suggestions': [s for s in suggestions if s]})
    except Exception:
        return JsonResponse({'suggestions': []})


# ── Home Feed ─────────────────────────────────────────────────────────────────

@require_GET
def home_feed(request):
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        rows = yt.get_home(limit=4)
        data = {'sections': []}
        for row in rows:
            title = row.get('title', '')
            contents = row.get('contents', [])
            if not contents:
                continue
            items = []
            for item in contents[:12]:
                if not isinstance(item, dict):
                    continue
                vid = item.get('videoId')
                if vid:
                    items.append(_normalize_song(item))
                else:
                    bid = item.get('browseId', item.get('playlistId', ''))
                    if bid:
                        items.append({
                            'id': bid,
                            'title': item.get('title', 'Unknown'),
                            'artist': _extract_artist_name(item.get('artists', item.get('author', ''))),
                            'thumbnail': _best_thumb(item.get('thumbnails', [])),
                            'type': 'playlist' if item.get('playlistId') else 'album',
                        })
            if items:
                data['sections'].append({'title': title, 'items': items})
        if not data['sections']:
            results = yt.search('top hits 2025', filter='songs', limit=20)
            normalized = _normalize_results(results, 'songs')
            if normalized:
                data['sections'].append({'title': 'Top Hits', 'items': normalized})
        return JsonResponse(data)
    except Exception as e:
        logger.exception('home_feed failed')
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


# ── Track / Lyrics / Related ──────────────────────────────────────────────────

@require_GET
def track_info(request, video_id):
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        info = yt.get_song(video_id)
        details = info.get('videoDetails') or info or {}
        thumbnails = (
            details.get('thumbnail', {}).get('thumbnails', [])
            or details.get('thumbnails', [])
            or info.get('thumbnails', [])
        )
        return JsonResponse({
            'id': video_id,
            'title': details.get('title') or info.get('title', 'Unknown'),
            'artist': details.get('author') or _extract_artist_name(info.get('artists', [])),
            'duration': int(details.get('lengthSeconds') or info.get('duration_seconds', 0) or 0),
            'thumbnail': _best_thumb(thumbnails),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def lyrics(request, video_id):
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        wp = yt.get_watch_playlist(video_id)
        lyrics_id = wp.get('lyrics')
        if not lyrics_id:
            return JsonResponse({'lyrics': None})
        lyr = yt.get_lyrics(lyrics_id)
        text = lyr.get('lyrics') if isinstance(lyr, dict) else getattr(lyr, 'lyrics', None)
        return JsonResponse({'lyrics': text})
    except Exception as e:
        return JsonResponse({'lyrics': None, 'error': str(e)})


@require_GET
def related_tracks(request, video_id):
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        wp = yt.get_watch_playlist(video_id, limit=20)
        tracks = wp.get('tracks', [])
        return JsonResponse({'tracks': [_normalize_song(t) for t in tracks if t and t.get('videoId')]})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ── Album / Playlist / Artist ─────────────────────────────────────────────────

@require_GET
def album_detail(request, browse_id):
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        album = yt.get_album(browse_id)
        tracks = album.get('tracks', [])
        return JsonResponse({
            'title': album.get('title', 'Unknown Album'),
            'artist': _extract_artist_name(album.get('artists', [])),
            'year': album.get('year'),
            'thumbnail': _best_thumb(album.get('thumbnails', [])),
            'tracks': [_normalize_song(t) for t in tracks if t],
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def playlist_detail(request, playlist_id):
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        pl = yt.get_playlist(playlist_id, limit=50)
        tracks = pl.get('tracks', [])
        author = pl.get('author', {})
        return JsonResponse({
            'id': playlist_id,
            'title': pl.get('title', 'Unknown Playlist'),
            'author': author.get('name', '') if isinstance(author, dict) else str(author),
            'description': pl.get('description', ''),
            'thumbnail': _best_thumb(pl.get('thumbnails', [])),
            'trackCount': pl.get('trackCount', len(tracks)),
            'tracks': [_normalize_song(t) for t in tracks if t and t.get('videoId')],
        })
    except Exception as e:
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


@require_GET
def artist_detail(request, channel_id):
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        artist = yt.get_artist(channel_id)
        songs = [_normalize_song(s) for s in artist.get('songs', {}).get('results', [])[:10] if s]
        albums = [
            {
                'id': a.get('browseId'), 'title': a.get('title'), 'year': a.get('year'),
                'thumbnail': _best_thumb(a.get('thumbnails', [])), 'type': 'album',
            }
            for a in artist.get('albums', {}).get('results', [])[:6]
        ]
        return JsonResponse({
            'name': artist.get('name', 'Unknown Artist'),
            'description': artist.get('description', ''),
            'thumbnail': _best_thumb(artist.get('thumbnails', [])),
            'songs': songs, 'albums': albums,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ── Stream — THE CRITICAL FIX ─────────────────────────────────────────────────
#
# WHY LOCAL WORKS BUT RAILWAY DOESN'T:
# yt-dlp's default 'web' client fetches a stream URL signed/bound to the
# requesting server's IP. On Railway (a known cloud datacenter), YouTube
# aggressively rejects or rate-limits these requests.
#
# THE FIX: Two-step approach
#   1. Use 'android_music' player client — far less blocked on cloud IPs,
#      and returns CDN URLs that are NOT IP-bound (the browser can use them)
#   2. Send an HTTP 302 redirect to that CDN URL — zero proxy overhead,
#      zero timeout risk, the browser fetches directly from YouTube's CDN

@require_GET
def stream_proxy(request, video_id):
    """
    Resolves YouTube audio stream using android_music client (cloud-safe),
    then redirects the browser directly to the CDN URL.
    Falls back to server-side proxying if redirect fails.
    """
    import time

    # Check cache first
    with _cache_lock:
        cached = _stream_cache.get(video_id)
        if cached and cached[1] > time.time():
            cdn_url = cached[0]
            logger.info(f'Stream cache hit for {video_id}')
            return _redirect_or_proxy(request, cdn_url)

    # Resolve stream URL with cloud-safe yt-dlp options
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
            info = ydl.extract_info(
                f'https://music.youtube.com/watch?v={video_id}',
                download=False
            )
            # Pick the best URL from the result
            cdn_url = _pick_best_url(info)
            if not cdn_url:
                raise ValueError('yt-dlp returned no stream URL')

        logger.info(f'Resolved stream for {video_id}: {cdn_url[:80]}…')

        with _cache_lock:
            _stream_cache[video_id] = (cdn_url, time.time() + 270)

        return _redirect_or_proxy(request, cdn_url)

    except Exception as e:
        logger.error(f'Stream resolution failed for {video_id}: {e}')
        return JsonResponse(
            {'error': f'Stream resolution failed: {e}', 'traceback': traceback.format_exc()},
            status=500
        )


def _pick_best_url(info: dict) -> str:
    """Extract the best audio-only stream URL from yt-dlp info dict."""
    # Direct URL on top-level (common for single-format extraction)
    if info.get('url'):
        return info['url']

    # Pick from formats list — prefer m4a audio, then webm audio, then best
    formats = info.get('formats', [])
    audio_formats = [
        f for f in formats
        if f.get('acodec') != 'none' and f.get('vcodec') in ('none', None, '')
    ]
    if audio_formats:
        # Sort by abr descending
        audio_formats.sort(key=lambda f: f.get('abr') or 0, reverse=True)
        return audio_formats[0].get('url', '')

    # Last resort: any format with a URL
    for f in reversed(formats):
        if f.get('url'):
            return f['url']

    return ''


def _redirect_or_proxy(request, cdn_url: str):
    """
    Primary strategy: redirect browser directly to CDN URL.
    The android_music client URLs are not IP-restricted — the browser
    can fetch them directly without going through our server.
    """
    # If the request has a Range header, the browser is seeking —
    # we must proxy because a redirect loses Range support in some browsers.
    if 'HTTP_RANGE' in request.META:
        return _proxy_stream(request, cdn_url)

    # Otherwise redirect — zero overhead, no timeout risk
    response = HttpResponseRedirect(cdn_url)
    response['Cache-Control'] = 'no-cache'
    return response


def _proxy_stream(request, cdn_url: str):
    """
    Fallback: pipe the stream through Django.
    Used for Range (seek) requests where redirect may lose the Range header.
    """
    import requests as req

    headers = {
        'User-Agent': (
            'com.google.android.apps.youtube.music/'
            '5.34.51 (Linux; U; Android 11) gzip'
        ),
        'Referer': 'https://music.youtube.com/',
        'Origin': 'https://music.youtube.com',
    }
    if 'HTTP_RANGE' in request.META:
        headers['Range'] = request.META['HTTP_RANGE']

    try:
        upstream = req.get(cdn_url, headers=headers, stream=True, timeout=20)
        content_type = upstream.headers.get('Content-Type', 'audio/mp4')
        response = StreamingHttpResponse(
            upstream.iter_content(chunk_size=65536),
            status=upstream.status_code,
            content_type=content_type,
        )
        for h in ('Content-Length', 'Content-Range', 'Accept-Ranges'):
            if h in upstream.headers:
                response[h] = upstream.headers[h]
        response['Accept-Ranges'] = 'bytes'
        response['Access-Control-Allow-Origin'] = '*'
        response['Cache-Control'] = 'no-cache'
        return response
    except Exception as e:
        return HttpResponse(f'Proxy error: {e}', status=502)


# Keep this endpoint for backwards compatibility / debug
@require_GET
def stream_url(request, video_id):
    """Returns the resolved stream URL as JSON (for debugging only)."""
    import time
    with _cache_lock:
        cached = _stream_cache.get(video_id)
        if cached and cached[1] > time.time():
            return JsonResponse({'url': cached[0], 'cached': True})
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
            info = ydl.extract_info(
                f'https://music.youtube.com/watch?v={video_id}', download=False
            )
            url = _pick_best_url(info)
            if not url:
                raise ValueError('No stream URL found')
        with _cache_lock:
            _stream_cache[video_id] = (url, time.time() + 270)
        return JsonResponse({'url': url, 'cached': False})
    except Exception as e:
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _best_thumb(thumbnails: list) -> str:
    if not thumbnails:
        return ''
    valid = [t for t in thumbnails if isinstance(t, dict)]
    return max(valid, key=lambda t: t.get('width', 0) * t.get('height', 0), default={}).get('url', '')


def _extract_artist_name(artists) -> str:
    if not artists:
        return 'Unknown Artist'
    if isinstance(artists, list):
        names = [a.get('name', '') for a in artists if isinstance(a, dict) and a.get('name')]
        return ', '.join(names) or 'Unknown Artist'
    return str(artists)


def _normalize_song(item: dict) -> dict:
    if not item:
        return {}
    dur = item.get('duration_seconds') or item.get('duration') or 0
    if isinstance(dur, str) and ':' in dur:
        parts = dur.split(':')
        try:
            dur = int(parts[-2]) * 60 + int(parts[-1])
        except Exception:
            dur = 0
    album = item.get('album') or {}
    return {
        'id': item.get('videoId') or item.get('id', ''),
        'title': item.get('title', 'Unknown'),
        'artist': _extract_artist_name(item.get('artists', [])),
        'album': album.get('name', '') if isinstance(album, dict) else str(album),
        'duration': int(dur),
        'thumbnail': _best_thumb(item.get('thumbnails', [])),
        'type': 'song',
    }


def _normalize_results(results: list, result_type: str) -> list:
    out = []
    for item in results:
        if not item:
            continue
        cat = item.get('resultType', result_type)
        if cat in ('song', 'video'):
            out.append(_normalize_song(item))
        elif cat == 'album':
            out.append({
                'id': item.get('browseId', ''), 'title': item.get('title', 'Unknown'),
                'artist': _extract_artist_name(item.get('artists', [])),
                'year': item.get('year'),
                'thumbnail': _best_thumb(item.get('thumbnails', [])), 'type': 'album',
            })
        elif cat == 'artist':
            out.append({
                'id': item.get('browseId', ''),
                'title': item.get('artist', item.get('title', 'Unknown Artist')),
                'thumbnail': _best_thumb(item.get('thumbnails', [])), 'type': 'artist',
            })
        elif cat == 'playlist':
            out.append({
                'id': item.get('browseId', ''), 'title': item.get('title', 'Unknown Playlist'),
                'artist': item.get('author', ''),
                'thumbnail': _best_thumb(item.get('thumbnails', [])), 'type': 'playlist',
            })
    return out
