/* Auto Assessments tab: registers the section with the legacy instructor dashboard
 * and renders the paged scores table. Server data is only ever written with
 * textContent (or setAttribute for title), never innerHTML. */
(function () {
  'use strict';

  var PAGE_SIZES = [10, 25, 50];
  var NO_ATTEMPT = 'No attempt yet';
  var BASE_TITLE = 'Auto Assessments';
  var FONT_LINK_ID = 'edl-inter-font';
  var FONT_URL = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';
  // Column widths in px, used for the table's minimum width so many assessments scroll sideways.
  var LEARNER_WIDTH = 200;
  var DATE_WIDTH = 96;
  var CRITERION_MIN_WIDTH = 136;

  var state = {page: 1, pageSize: 10, q: '', assessment: '', loaded: false, requestId: 0, timer: null, courseName: ''};
  var els = {};

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function root() { return document.querySelector('#auto_assessments .edl-aa'); }

  // Inter comes from Google Fonts. If it is blocked the CSS falls back to the system font.
  function loadFont() {
    if (document.getElementById(FONT_LINK_ID)) { return; }
    var connect = el('link');
    connect.rel = 'preconnect';
    connect.href = 'https://fonts.googleapis.com';
    var connectStatic = el('link');
    connectStatic.rel = 'preconnect';
    connectStatic.href = 'https://fonts.gstatic.com';
    connectStatic.crossOrigin = 'anonymous';
    var sheet = el('link');
    sheet.id = FONT_LINK_ID;
    sheet.rel = 'stylesheet';
    sheet.href = FONT_URL;
    document.head.appendChild(connect);
    document.head.appendChild(connectStatic);
    document.head.appendChild(sheet);
  }

  function srLabel(text, forId) {
    var label = el('label', 'sr-only', text);
    label.setAttribute('for', forId);
    return label;
  }

  // Always the whole course: the link carries no search or assessment filter.
  function buildDownload(host) {
    var link = el('a', 'edl-aa-download', 'Download CSV');
    link.href = withZone(host.getAttribute('data-csv-url'));
    return link;
  }

  function buildControls(host) {
    var tableRoot = host.querySelector('.edl-aa-table-root');
    els.title = host.querySelector('.edl-aa-title');
    els.intro = host.querySelector('.edl-aa-intro');
    var bar = el('div', 'edl-aa-bar');

    els.search = el('input', 'edl-aa-search');
    els.search.id = 'edl-aa-search';
    els.search.type = 'search';
    els.search.placeholder = 'Name, username or email';
    els.search.addEventListener('input', function () {
      window.clearTimeout(state.timer);
      state.timer = window.setTimeout(function () {
        state.q = els.search.value.trim();
        state.page = 1;
        fetchPage();
      }, 300);
    });

    els.clear = el('button', 'edl-aa-clear', 'Clear filters');
    els.clear.type = 'button';
    els.clear.hidden = true;
    els.clear.addEventListener('click', function () {
      window.clearTimeout(state.timer);
      els.search.value = '';
      state.q = '';
      state.page = 1;
      fetchPage();
      els.search.focus();
    });

    els.select = el('select', 'edl-aa-assessment');
    els.select.id = 'edl-aa-assessment';
    els.select.appendChild(new Option('All assessments', ''));
    els.select.addEventListener('change', function () {
      state.assessment = els.select.value;
      state.page = 1;
      fetchPage();
    });

    bar.appendChild(srLabel('Search learners', els.search.id));
    bar.appendChild(els.search);
    bar.appendChild(els.clear);
    bar.appendChild(srLabel('Assessment', els.select.id));
    bar.appendChild(els.select);
    bar.appendChild(buildDownload(host));

    // Replace the no-JavaScript fallback link with this button.
    var fallback = host.querySelector('.edl-aa-download-fallback');
    if (fallback) { fallback.remove(); }
    tableRoot.appendChild(bar);

    els.status = el('div', 'edl-aa-status');
    els.status.setAttribute('role', 'status');
    els.scroll = el('div', 'edl-aa-scroll');
    els.scroll.tabIndex = 0;
    els.scroll.setAttribute('role', 'region');
    els.scroll.setAttribute('aria-label', 'Learner scores table, scrolls sideways');
    els.footer = el('div', 'edl-aa-footer');
    tableRoot.appendChild(els.status);
    tableRoot.appendChild(els.scroll);
    tableRoot.appendChild(els.footer);
  }

  // The course name is the competency of every column (see get_columns), so no extra field is needed.
  function setHeading(payload) {
    if (payload.columns.length) { state.courseName = payload.columns[0].competency || ''; }
    els.title.textContent = state.courseName ? BASE_TITLE + ' for ' + state.courseName : BASE_TITLE;
    els.intro.textContent = 'Scores for each learning criterion. A criterion is Demonstrated at ' +
      payload.threshold + '% or more.';
  }

  // Rebuilt on every response so the counts stay current. The selected option is kept.
  function setAssessments(assessments) {
    var selected = state.assessment;
    els.select.textContent = '';
    els.select.appendChild(new Option('All assessments (' + assessments.length + ' assessments)', ''));
    assessments.forEach(function (a) {
      els.select.appendChild(new Option(a.name + ' (' + a.attempted + ' of ' + a.total + ' attempted)', a.id));
    });
    els.select.value = selected;
  }

  function setClear() { els.clear.hidden = !state.q; }

  function noMatch() {
    var box = el('div', 'edl-aa-nomatch');
    box.appendChild(el('strong', null, 'No learners match'));
    box.appendChild(document.createTextNode('Try a different search.'));
    return box;
  }

  function dateCell(info) {
    var td = el('td', 'edl-aa-date edl-aa-group-start');
    td.appendChild(el('div', 'edl-aa-date-text', info.date));
    if (info.note) { td.appendChild(el('div', 'edl-aa-date-note', info.note)); }
    return td;
  }

  function scoreCell(cell) {
    var td = el('td');
    if (cell === null) {
      td.className = 'edl-aa-none';
      td.textContent = NO_ATTEMPT;
      return td;
    }
    var demonstrated = cell.status === 'demonstrated';
    td.className = demonstrated ? 'edl-aa-demonstrated' : 'edl-aa-not-demonstrated';
    td.appendChild(el('div', 'edl-aa-pct', cell.percent + '%'));
    td.appendChild(el('div', 'edl-aa-label', demonstrated ? 'Demonstrated' : 'Not demonstrated'));
    return td;
  }

  function learnerCell(learner) {
    var th = el('th', 'edl-aa-sticky edl-aa-learner');
    th.scope = 'row';
    th.appendChild(el('strong', null, learner.name));
    th.appendChild(el('div', 'edl-aa-sub', learner.username));
    var email = el('div', 'edl-aa-email', learner.email);
    email.setAttribute('title', learner.email);
    th.appendChild(email);
    return th;
  }

  // Splits the flat column list into one block per assessment: {id, name, start, count}.
  function groupColumns(columns) {
    var blocks = [];
    columns.forEach(function (c, idx) {
      var last = blocks[blocks.length - 1];
      if (last && last.id === c.block_id) {
        last.count += 1;
      } else {
        blocks.push({id: c.block_id, name: c.assessment, start: idx, count: 1});
      }
    });
    return blocks;
  }

  function buildColgroup(blocks) {
    var colgroup = el('colgroup');
    colgroup.appendChild(el('col', 'edl-aa-col-learner'));
    blocks.forEach(function (block) {
      colgroup.appendChild(el('col', 'edl-aa-col-date'));
      for (var n = 0; n < block.count; n += 1) { colgroup.appendChild(el('col')); }
    });
    return colgroup;
  }

  function buildHead(columns, blocks) {
    var head = el('thead');
    var row1 = el('tr');
    var row2 = el('tr');

    var learnerHead = el('th', 'edl-aa-sticky edl-aa-learner-head', 'Learner');
    learnerHead.rowSpan = 2;
    learnerHead.scope = 'col';
    row1.appendChild(learnerHead);

    blocks.forEach(function (block) {
      var group = el('th', 'edl-aa-group');
      group.appendChild(el('span', 'edl-aa-group-title', block.name));
      group.colSpan = block.count + 1;  // plus the "Attempt date" column
      group.scope = 'colgroup';
      row1.appendChild(group);

      var dateHead = el('th', 'edl-aa-date-head edl-aa-group-start', 'Attempt date');
      dateHead.scope = 'col';
      row2.appendChild(dateHead);
      for (var n = block.start; n < block.start + block.count; n += 1) {
        var th = el('th', 'edl-aa-criterion', columns[n].criterion);
        th.scope = 'col';
        row2.appendChild(th);
      }
    });
    head.appendChild(row1);
    head.appendChild(row2);
    return head;
  }

  function buildRow(learner, blocks) {
    var tr = el('tr');
    tr.appendChild(learnerCell(learner));
    blocks.forEach(function (block) {
      var info = (learner.dates || {})[block.id];
      if (!info || !info.date) {
        // One merged cell per assessment, never per row.
        var none = el('td', 'edl-aa-none edl-aa-group-start', NO_ATTEMPT);
        none.colSpan = block.count + 1;
        tr.appendChild(none);
        return;
      }
      tr.appendChild(dateCell(info));
      for (var n = block.start; n < block.start + block.count; n += 1) {
        tr.appendChild(scoreCell(learner.cells[n]));
      }
    });
    return tr;
  }

  function renderTable(payload) {
    els.scroll.textContent = '';
    if (!payload.columns.length) {
      els.status.textContent = 'No auto assessment scores are available for this course yet.';
      return;
    }
    if (!payload.learners.length) {
      els.status.textContent = '';
      els.scroll.appendChild(state.q ? noMatch() : el('div', 'edl-aa-nomatch', 'No learners found.'));
      return;
    }
    els.status.textContent = '';

    var blocks = groupColumns(payload.columns);
    var table = el('table', 'edl-aa-table');
    table.style.minWidth = (LEARNER_WIDTH + blocks.length * DATE_WIDTH +
      payload.columns.length * CRITERION_MIN_WIDTH) + 'px';
    table.appendChild(buildColgroup(blocks));
    table.appendChild(buildHead(payload.columns, blocks));

    var body = el('tbody');
    payload.learners.forEach(function (learner) { body.appendChild(buildRow(learner, blocks)); });
    table.appendChild(body);
    els.scroll.appendChild(table);
  }

  function pageButton(label, page, disabled, current) {
    var button = el('button', 'edl-aa-page' + (current ? ' edl-aa-current' : ''), label);
    button.type = 'button';
    button.disabled = !!disabled;
    if (current) { button.setAttribute('aria-current', 'page'); }
    button.addEventListener('click', function () {
      state.page = page;
      fetchPage();
    });
    return button;
  }

  function renderFooter(payload) {
    els.footer.textContent = '';
    var info = el('span', 'edl-aa-info', 'Showing ' + payload.learners.length + ' of ' + payload.total + ' learners');
    info.setAttribute('role', 'status');
    els.footer.appendChild(info);

    var size = el('select', 'edl-aa-size');
    size.setAttribute('aria-label', 'Rows per page');
    PAGE_SIZES.forEach(function (n) {
      var option = new Option(n + ' per page', n);
      option.selected = n === payload.page_size;
      size.appendChild(option);
    });
    size.addEventListener('change', function () {
      state.pageSize = parseInt(size.value, 10);
      state.page = 1;
      fetchPage();
    });
    els.footer.appendChild(size);

    var pager = el('span', 'edl-aa-pager');
    pager.appendChild(pageButton('Previous', payload.page - 1, payload.page <= 1));
    for (var p = Math.max(1, payload.page - 2); p <= Math.min(payload.num_pages, payload.page + 2); p += 1) {
      pager.appendChild(pageButton(String(p), p, false, p === payload.page));
    }
    pager.appendChild(pageButton('Next', payload.page + 1, payload.page >= payload.num_pages));
    els.footer.appendChild(pager);
  }

  // The viewer's IANA time zone (for example "America/Chicago"). The server writes every date in it.
  function browserZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return ''; }
  }

  function withZone(url) {
    var zone = browserZone();
    if (!url || !zone) { return url; }
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'tz=' + encodeURIComponent(zone);
  }

  function fetchPage() {
    var host = root();
    if (!host) { return; }
    var url = host.getAttribute('data-data-url');
    if (!url) { return; }

    state.requestId += 1;
    var requestId = state.requestId;
    var params = new URLSearchParams({
      page: state.page, page_size: state.pageSize, q: state.q, assessment: state.assessment, tz: browserZone()
    });
    els.status.textContent = 'Loading...';
    setClear();

    fetch(url + '?' + params.toString(), {credentials: 'same-origin'})
      .then(function (response) {
        if (!response.ok) { throw new Error('HTTP ' + response.status); }
        return response.json();
      })
      .then(function (payload) {
        if (requestId !== state.requestId) { return; }  // a newer request replaced this one
        state.page = payload.page;
        setHeading(payload);
        setAssessments(payload.assessments);
        renderTable(payload);
        renderFooter(payload);
      })
      .catch(function () {
        if (requestId !== state.requestId) { return; }
        els.scroll.textContent = '';
        els.footer.textContent = '';
        els.status.textContent = 'Could not load scores. Try again.';
      });
  }

  window.EdlAutoAssessments = {
    load: function () {
      var host = root();
      if (!host || state.loaded || !host.getAttribute('data-data-url')) { return; }
      state.loaded = true;
      loadFont();
      buildControls(host);
      fetchPage();
    }
  };

  // The dashboard calls $section.data('wrapper').onClickTitle() on every tab click and
  // throws for a section it does not know, so give the section a wrapper.
  function init() {
    var section = window.jQuery && window.jQuery('#auto_assessments');
    if (!section || !section.length) { return false; }
    if (!section.data('wrapper')) {
      section.data('wrapper', {
        onClickTitle: function () { window.EdlAutoAssessments.load(); },
        onExit: function () {}
      });
    }
    return true;
  }
  if (!init()) { document.addEventListener('DOMContentLoaded', init); }
})();
