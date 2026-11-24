"""App configuration for the EDL plugin in LMS and Studio."""

from django.apps import AppConfig
from django.conf import settings


class EdlPluginConfig(AppConfig):
    """
    Open edX plugin AppConfig.

    Registers the plugin's LMS URLs (mounted at the site root so the full
    ``/courses/<course_id>/instructor/auto_assessments/...`` paths resolve) and
    its settings hook (which wires the instructor-dashboard render filter and
    the Mako template directory). Studio only uses the rerun patches.
    Uses raw string keys instead of the
    ``PluginURLs``/``PluginSettings`` constants so the package imports cleanly
    without a hard dependency on a specific edx-platform module path.
    """

    name = "edl_plugin"
    verbose_name = "EDL Plugin"

    plugin_app = {
        "url_config": {
            "lms.djangoapp": {
                "namespace": "edl_plugin",
                "regex": r"",
                "relative_path": "urls",
            },
        },
        "settings_config": {
            "lms.djangoapp": {
                "common": {"relative_path": "settings.common"},
                "production": {"relative_path": "settings.common"},
                "devstack": {"relative_path": "settings.common"},
            },
            "cms.djangoapp": {},
        },
    }

    def ready(self):
        """Install course rerun patches only in Studio."""
        # Ulmo uses cms.urls for Studio even when SERVICE_VARIANT is overridden.
        if getattr(settings, "ROOT_URLCONF", None) == "cms.urls":
            from .course_rerun.patches import apply_patches

            apply_patches()
