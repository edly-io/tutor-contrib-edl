/* Auto Assessments tab: registers the section with the legacy instructor dashboard
 * and renders the paged scores table. Server data is only ever written with
 * textContent, never innerHTML. */
(function () {
  'use strict';

  var PAGE_SIZES = [10, 25, 50];
  var state = {page: 1, pageSize: 10, q: '', assessment: '', loaded: false, requestId: 0, timer: null};
  var els = {};

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function root() { return document.querySelector('#auto_assessments .edl-aa'); }

  function buildControls(host) {
    var bar = el('div', 'edl-aa-bar');

    els.search = el('input', 'edl-aa-search');
    els.search.type = 'search';
    els.search.placeholder = 'Search name, username or email';
    els.search.setAttribute('aria-label', 'Search learners');
    els.search.addEventListener('input', function () {
      window.clearTimeout(state.timer);
      state.timer = window.setTimeout(function () {
        state.q = els.search.value.trim();
        state.page = 1;
        fetchPage();
      }, 300);
    });

    els.select = el('select', 'edl-aa-assessment');
    els.select.setAttribute('aria-label', 'Filter by assessment');
    els.select.appendChild(new Option('All assessments', ''));
    els.select.addEventListener('change', function () {
      state.assessment = els.select.value;
      state.page = 1;
      fetchPage();
    });

    els.legend = el('span', 'edl-aa-legend');
    bar.appendChild(els.search);
    bar.appendChild(els.select);
    bar.appendChild(els.legend);

    var download = host.querySelector('.edl-aa-download');
    if (download) { bar.appendChild(download); }
    host.querySelector('.edl-aa-table-root').appendChild(bar);

    els.status = el('div', 'edl-aa-status');
    els.scroll = el('div', 'edl-aa-scroll');
    els.footer = el('div', 'edl-aa-footer');
    var tableRoot = host.querySelector('.edl-aa-table-root');
    tableRoot.appendChild(els.status);
    tableRoot.appendChild(els.scroll);
    tableRoot.appendChild(els.footer);
  }

  function setLegend(threshold) {
    els.legend.textContent = '';
    els.legend.appendChild(el('span', 'edl-aa-chip edl-aa-demonstrated', 'Demonstrated ' + threshold + '% or more'));
    els.legend.appendChild(el('span', 'edl-aa-chip edl-aa-not-demonstrated', 'Not Demonstrated below ' + threshold + '%'));
  }

  function setAssessments(assessments) {
    if (els.select.options.length > 1) { return; }  // keep the full list across filtered responses
    assessments.forEach(function (a) { els.select.appendChild(new Option(a.name, a.id)); });
  }

  function renderTable(payload) {
    els.scroll.textContent = '';
    if (!payload.columns.length) {
      els.status.textContent = 'No auto assessment scores are available for this course yet.';
      return;
    }
    if (!payload.learners.length) {
      els.status.textContent = 'No learners found.';
      return;
    }
    els.status.textContent = '';

    var table = el('table', 'edl-aa-table');
    var head = el('thead');
    var row1 = el('tr');
    var row2 = el('tr');

    var learnerHead = el('th', 'edl-aa-sticky edl-aa-learner-head', 'Learner');
    learnerHead.rowSpan = 2;
    learnerHead.scope = 'col';
    row1.appendChild(learnerHead);

    var i = 0;
    while (i < payload.columns.length) {
      var blockId = payload.columns[i].block_id;
      var start = i;
      while (i < payload.columns.length && payload.columns[i].block_id === blockId) { i += 1; }
      var group = el('th', 'edl-aa-group', payload.columns[start].assessment);
      group.colSpan = i - start;
      group.scope = 'colgroup';
      row1.appendChild(group);
    }
    payload.columns.forEach(function (c) {
      var th = el('th', 'edl-aa-criterion', c.criterion);
      th.scope = 'col';
      row2.appendChild(th);
    });
    head.appendChild(row1);
    head.appendChild(row2);
    table.appendChild(head);

    var body = el('tbody');
    payload.learners.forEach(function (learner) {
      var tr = el('tr');
      var th = el('th', 'edl-aa-sticky edl-aa-learner');
      th.scope = 'row';
      th.appendChild(el('strong', null, learner.name));
      th.appendChild(el('div', 'edl-aa-sub', learner.username));
      th.appendChild(el('div', 'edl-aa-sub', learner.email));
      tr.appendChild(th);
      learner.cells.forEach(function (cell) {
        var td = el('td');
        if (cell === null) {
          td.className = 'edl-aa-empty';
        } else {
          var demonstrated = cell.status === 'demonstrated';
          td.className = demonstrated ? 'edl-aa-demonstrated' : 'edl-aa-not-demonstrated';
          td.appendChild(el('div', 'edl-aa-pct', cell.percent + '%'));
          td.appendChild(el('div', 'edl-aa-label', demonstrated ? 'Demonstrated' : 'Not Demonstrated'));
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
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
    var first = payload.total ? (payload.page - 1) * payload.page_size + 1 : 0;
    var last = Math.min(payload.page * payload.page_size, payload.total);
    els.footer.appendChild(el('span', 'edl-aa-info', 'Showing learners ' + first + ' to ' + last + ' of ' + payload.total));

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

  function fetchPage() {
    var host = root();
    if (!host) { return; }
    var url = host.getAttribute('data-data-url');
    if (!url) { return; }

    state.requestId += 1;
    var requestId = state.requestId;
    var params = new URLSearchParams({
      page: state.page, page_size: state.pageSize, q: state.q, assessment: state.assessment
    });
    els.status.textContent = 'Loading...';

    fetch(url + '?' + params.toString(), {credentials: 'same-origin'})
      .then(function (response) {
        if (!response.ok) { throw new Error('HTTP ' + response.status); }
        return response.json();
      })
      .then(function (payload) {
        if (requestId !== state.requestId) { return; }  // a newer request replaced this one
        state.page = payload.page;
        setLegend(payload.threshold);
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
