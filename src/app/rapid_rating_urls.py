from django.urls import path

from app.rapid_rating import rapid_rating

urlpatterns = [
    path("rapid-rate/", rapid_rating, name="rapid_rating"),
]
