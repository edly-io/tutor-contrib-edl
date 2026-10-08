/* Auto Assessments tab. Registers the section with the legacy instructor dashboard. */
(function () {
  // The dashboard calls $section.data('wrapper').onClickTitle() on every tab click and
  // throws for a section it does not know, so give the section a wrapper.
  function init() {
    var el = window.jQuery && window.jQuery('#auto_assessments');
    if (!el || !el.length) { return false; }
    if (!el.data('wrapper')) {
      el.data('wrapper', {
        onClickTitle: function () {
          if (window.EdlAutoAssessments) { window.EdlAutoAssessments.load(); }
        },
        onExit: function () {}
      });
    }
    return true;
  }
  if (!init()) { document.addEventListener('DOMContentLoaded', init); }
})();
