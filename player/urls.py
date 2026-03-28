from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('api/debug/', views.debug, name='debug'),
    path('api/search/', views.search, name='search'),
    path('api/search/suggestions/', views.search_suggestions, name='search_suggestions'),
    path('api/home/', views.home_feed, name='home_feed'),
    path('api/track/<str:video_id>/', views.track_info, name='track_info'),
    path('api/track/<str:video_id>/lyrics/', views.lyrics, name='lyrics'),
    path('api/track/<str:video_id>/related/', views.related_tracks, name='related_tracks'),
    path('api/stream/<str:video_id>/', views.stream_url, name='stream_url'),
    path('api/proxy/<str:video_id>/', views.stream_proxy, name='stream_proxy'),
    path('api/album/<str:browse_id>/', views.album_detail, name='album_detail'),
    path('api/playlist/<str:playlist_id>/', views.playlist_detail, name='playlist_detail'),
    path('api/artist/<str:channel_id>/', views.artist_detail, name='artist_detail'),
]
