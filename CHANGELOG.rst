Change Log
##########

..
   All enhancements and patches to edl_plugin will be documented
   in this file.  It adheres to the structure of https://keepachangelog.com/ ,
   but in reStructuredText instead of Markdown (for ease of incorporation into
   Sphinx documentation and the PyPI description).

   This project adheres to Semantic Versioning (https://semver.org/).

.. There should always be an "Unreleased" section for changes pending release.

Unreleased
**********

Added
=====

* Add an "Attempt date" column (for example "Oct 20, 2026", in the viewer's browser time zone) as the first column of every assessment in the Auto Assessments table and CSV.
* Add ``attempted`` and ``total`` (learners with a graded attempt, and all active enrollees, over the whole course) to each ``assessments`` item of the data JSON.
* Add a "Clear filters" button while a search is active, a "Showing X of Y learners" count line and a "No learners match" empty state.
* Allow Studio users to rerun courses they can edit when they have a course creation grant for the course's organization (EDLINTERNA-32).

Changed
=======

* Write the Attempt Date in the viewer's browser time zone, on screen and in the CSV. The browser sends its time zone as ``tz`` and an unknown or missing value falls back to UTC.
* Redesign the scores table: one toolbar row (search, assessment, Download CSV), no legend, lighter colours, plain headers without hyphenation, a learner column with a one-line email that shows in full on hover, and faint dividers between criteria with stronger ones between assessments.
* Show "No attempt yet" instead of "No score" in empty cells. A learner with no attempt in an assessment gets one merged cell across that assessment.
* Replace the Competency band in the table with the page heading "Auto Assessments for <course name>". The CSV keeps its Competency row.
* Show the attempted count in the assessment dropdown ("<name> (X of Y attempted)") and start on "All assessments".
* Write the date as "Oct 20, 2026" on screen and in the CSV (was MM/DD/YYYY).
* Write the status as "Not demonstrated" (sentence case) on screen and in the CSV, for example ``40% (Not demonstrated)``.
* Load the Inter font from Google Fonts. The table falls back to the system font if it is blocked.
* Add a Competency row (the course title) above the assessment name in the CSV. The CSV header is now three rows.
* Show the Auto Assessments tab only for courses with LTI blocks.
* Polish the scores table styling.
* Show percents with up to 2 decimals (half up) instead of whole numbers.
  Demonstrated is decided on the displayed value.
* Build the CSV from plain score values instead of model instances, and load the
  course tree once per request, to cut memory and time on large courses.

Fixed
=====

* CSV: also escape cells that start with a tab or carriage return.
* CI: put the repo root on pytest's path so ``test_settings`` is found.

0.1.1 – 2026-10-08
**********************************************

Added
=====

* Leave the overall ``grade`` line item out of the report, configurable through
  ``EDL_AUTO_ASSESSMENT_EXCLUDED_LABELS``.

0.1.0 – 2026-10-08
**********************************************

Added
=====

* First release on PyPI.
