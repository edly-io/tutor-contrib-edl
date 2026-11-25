"""Studio API routes."""

from django.urls import path

from .course_creator_api.views import CourseCreatorAccessView

app_name = "edl_plugin_cms"
urlpatterns = [path("v1/course-creator/<str:username>/", CourseCreatorAccessView.as_view(), name="course-creator")]
