# Railway Procfile
# --timeout 120    : yt-dlp URL resolution can take 5-20s, need headroom
# --workers 2      : enough for concurrent stream resolves
# --threads 4      : handle concurrent requests within each worker
# --worker-class gthread : thread-based, better for I/O-bound streaming
web: gunicorn simpmusic.wsgi:application --bind 0.0.0.0:$PORT --timeout 120 --workers 2 --threads 4 --worker-class gthread --log-level info
