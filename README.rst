tutor-contrib-edl
=================

EDL Open edX LMS plugin. The first feature is the **Auto Assessments** tab on the
instructor dashboard: it shows and downloads the per-criterion scores that Muzzy
Lane posts over LTI 1.3 AGS (one score per learning criterion per assessment),
which the gradebook cannot keep because each line item overwrites the block grade.

How it works
------------

* **Tab**: an ``InstructorDashboardRenderStarted`` filter step
  (``edl_plugin.auto_assessment_scores.pipeline.AddAutoAssessmentsTab``) appends an
  ``auto_assessments`` section with its own Mako template. Shown only to users with
  course staff access.
* **Download**: ``/courses/<course_id>/instructor/auto_assessments/csv``, built in
  the request from ``LtiAgsLineItem`` and ``LtiAgsScore``. Course staff only.
* **CSV layout**: one row per learner, one column per learning criterion. Row 1
  repeats the assessment name above each of its criteria, row 2 holds
  ``Learner, Username, Email`` and the criteria names.
* **Cells**: ``87% (Demonstrated)`` or ``53% (Not Demonstrated)``. Demonstrated at
  or above ``EDL_AUTO_ASSESSMENT_THRESHOLD`` (default 75). Blank means no fully
  graded score.
* **Excluded labels**: line items whose label is in
  ``EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS`` (default ``["grade"]``, compared
  case-insensitively) are left out. ``grade`` is the overall line item some launch
  paths add next to the per-criterion ones.

Installation
------------

.. code-block:: bash

    pip install -e /path/to/tutor-contrib-edl

Then restart the LMS. The plugin is auto-discovered through the ``lms.djangoapp``
entry point. In Tutor, add the git URL to ``OPENEDX_EXTRA_PIP_REQUIREMENTS``.

Tests
-----

.. code-block:: bash

    pip install django pytest pytest-django pytest-cov web-fragments openedx-filters
    pytest
