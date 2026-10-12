"""App configuration that registers this package as an Open edX LMS plugin."""

from django.apps import AppConfig


class EdlPluginConfig(AppConfig):
    """
    Open edX plugin AppConfig.

    Registers the plugin's URLs (mounted at the site root so the full
    ``/courses/<course_id>/instructor/auto_assessments/...`` paths resolve) and
    its settings hook (which wires the instructor-dashboard render filter and
    the Mako template directory). Uses raw string keys instead of the
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
        },
    }
