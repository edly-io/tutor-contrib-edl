"""Constants for the auto assessment scores report."""

STATUS_DEMONSTRATED = "demonstrated"
STATUS_NOT_DEMONSTRATED = "not_demonstrated"
STATUS_LABELS = {
    STATUS_DEMONSTRATED: "Demonstrated",
    STATUS_NOT_DEMONSTRATED: "Not Demonstrated",
}

DEFAULT_THRESHOLD = 75

SECTION_KEY = "auto_assessments"
SECTION_DISPLAY_NAME = "Auto Assessments"
# The dashboard includes "<prefix><section_key>.html" through the Mako lookup.
TEMPLATE_PREFIX = "/edl_plugin/"
# Only added by the LMS when the user has course staff access.
STAFF_ONLY_SECTION_KEY = "course_info"
