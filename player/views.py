"""
SimpMusic Player Views — v3
"""
import traceback
import threading
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse
from django.views.decorators.http import require_GET
from django.shortcuts import render

_stream_cache: dict = {}
_cache_lock = threading.Lock()


def index(request):
    return render(request, 'player/index.html')


@require_GET
def debug(request):
    import sys
    result = {'python': sys.version, 'packages': {}}
    for pkg in ('ytmusicapi', 'yt_dlp', 'requests'):
        try:
            mod = __import__(pkg)
            result['packages'][pkg] = getattr(mod, '__version__', 'ok')
        except Exception as e:
            result['packages'][pkg] = f'MISSING: {e}'
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        sr = yt.search('Coldplay', filter='songs', limit=2)
        result['search_test'] = f'OK - {len(sr)} results'
    except Exception as e:
        result['search_test'] = f'FAILED: {e}\n{traceback.format_exc()}'
    return JsonResponse(result)


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
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


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
            results = yt.search('top hits 2024', filter='songs', limit=20)
            normalized = _normalize_results(results, 'songs')
            if normalized:
                data['sections'].append({'title': 'Top Hits', 'items': normalized})
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


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
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


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
        if isinstance(lyr, dict):
            text = lyr.get('lyrics')
        else:
            text = getattr(lyr, 'lyrics', None)
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
        normalized = [_normalize_song(t) for t in tracks if t and t.get('videoId')]
        return JsonResponse({'tracks': normalized})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


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
        songs = []
        if 'songs' in artist and 'results' in artist.get('songs', {}):
            songs = [_normalize_song(s) for s in artist['songs']['results'][:10] if s]
        albums = []
        if 'albums' in artist and 'results' in artist.get('albums', {}):
            for a in artist['albums']['results'][:6]:
                albums.append({
                    'id': a.get('browseId'),
                    'title': a.get('title'),
                    'year': a.get('year'),
                    'thumbnail': _best_thumb(a.get('thumbnails', [])),
                    'type': 'album',
                })
        return JsonResponse({
            'name': artist.get('name', 'Unknown Artist'),
            'description': artist.get('description', ''),
            'thumbnail': _best_thumb(artist.get('thumbnails', [])),
            'songs': songs,
            'albums': albums,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def stream_url(request, video_id):
    import time
    with _cache_lock:
        cached = _stream_cache.get(video_id)
        if cached and cached[1] > time.time():
            return JsonResponse({'url': cached[0], 'cached': True})
    try:
        import yt_dlp
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f'https://music.youtube.com/watch?v={video_id}',
                download=False
            )
            url = info.get('url') or (info.get('formats') or [{}])[-1].get('url', '')
            if not url:
                raise ValueError('No stream URL found')
        with _cache_lock:
            _stream_cache[video_id] = (url, time.time() + 270)
        return JsonResponse({'url': url, 'cached': False})
    except Exception as e:
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


@require_GET
def stream_proxy(request, video_id):
    import time
    import requests as req

    with _cache_lock:
        cached = _stream_cache.get(video_id)
        audio_url = cached[0] if (cached and cached[1] > time.time()) else None

    if not audio_url:
        try:
            import yt_dlp
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio',
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(
                    f'https://music.youtube.com/watch?v={video_id}',
                    download=False
                )
                audio_url = info.get('url') or (info.get('formats') or [{}])[-1].get('url', '')
            with _cache_lock:
                _stream_cache[video_id] = (audio_url, time.time() + 270)
        except Exception as e:
            return HttpResponse(f'Stream resolution failed: {e}', status=500)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://music.youtube.com/',
        'Origin': 'https://music.youtube.com',
    }
    if 'HTTP_RANGE' in request.META:
        headers['Range'] = request.META['HTTP_RANGE']

    try:
        upstream = req.get(audio_url, headers=headers, stream=True, timeout=15)
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
        response['Cache-Control'] = 'no-cache'
        response['Access-Control-Allow-Origin'] = '*'
        return response
    except Exception as e:
        return HttpResponse(f'Proxy error: {e}', status=502)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _best_thumb(thumbnails: list) -> str:
    if not thumbnails:
        return ''
    valid = [t for t in thumbnails if isinstance(t, dict)]
    sorted_thumbs = sorted(valid, key=lambda t: t.get('width', 0) * t.get('height', 0), reverse=True)
    return sorted_thumbs[0].get('url', '') if sorted_thumbs else ''


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
    thumbnails = item.get('thumbnails', [])
    artists = item.get('artists', [])
    video_id = item.get('videoId') or item.get('id', '')
    album = item.get('album') or {}
    dur = item.get('duration_seconds') or item.get('duration') or 0
    if isinstance(dur, str) and ':' in dur:
        parts = dur.split(':')
        try:
            dur = int(parts[-2]) * 60 + int(parts[-1]) if len(parts) >= 2 else 0
        except Exception:
            dur = 0
    return {
        'id': video_id,
        'title': item.get('title', 'Unknown'),
        'artist': _extract_artist_name(artists),
        'album': album.get('name', '') if isinstance(album, dict) else str(album),
        'duration': int(dur),
        'thumbnail': _best_thumb(thumbnails),
        'type': 'song',
    }


def _normalize_results(results: list, result_type: str) -> list:
    normalized = []
    for item in results:
        if not item:
            continue
        cat = item.get('resultType', result_type)
        if cat in ('song', 'video'):
            normalized.append(_normalize_song(item))
        elif cat == 'album':
            normalized.append({
                'id': item.get('browseId', ''),
                'title': item.get('title', 'Unknown'),
                'artist': _extract_artist_name(item.get('artists', [])),
                'year': item.get('year'),
                'thumbnail': _best_thumb(item.get('thumbnails', [])),
                'type': 'album',
            })
        elif cat == 'artist':
            normalized.append({
                'id': item.get('browseId', ''),
                'title': item.get('artist', item.get('title', 'Unknown Artist')),
                'thumbnail': _best_thumb(item.get('thumbnails', [])),
                'type': 'artist',
            })
        elif cat == 'playlist':
            normalized.append({
                'id': item.get('browseId', ''),
                'title': item.get('title', 'Unknown Playlist'),
                'artist': item.get('author', ''),
                'thumbnail': _best_thumb(item.get('thumbnails', [])),
                'type': 'playlist',
            })
    return normalized
