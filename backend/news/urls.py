from django.urls import path

from news.views import NewsListView

urlpatterns = [
    path("gold/", NewsListView.as_view(), name="news-list"),
]
