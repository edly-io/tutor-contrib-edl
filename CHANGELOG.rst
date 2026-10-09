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

Changed
=======

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
