/* officer.js — Bảng điều hành cán bộ khuyến nông
   Fetch API thuần, không thư viện ngoài.
   Mọi dữ liệu từ API đều đi qua textContent — không dùng innerHTML với input người dùng. */

'use strict';

// ─── Hằng số & cấu hình ─────────────────────────────────────────────────────

const REFRESH_INTERVAL_MS = 15000;
const TOAST_DURATION_MS   = 4500;
const TOAST_FADE_MS       = 280;
const HISTORY_PAGE_SIZE   = 5;

const REGION_NAMES = {
  an_giang:        'An Giang',
  ba_ria_vung_tau: 'Bà Rịa - Vũng Tàu',
  bac_giang:       'Bắc Giang',
  bac_kan:         'Bắc Kạn',
  bac_lieu:        'Bạc Liêu',
  bac_ninh:        'Bắc Ninh',
  ben_tre:         'Bến Tre',
  binh_dinh:       'Bình Định',
  binh_duong:      'Bình Dương',
  binh_phuoc:      'Bình Phước',
  binh_thuan:      'Bình Thuận',
  ca_mau:          'Cà Mau',
  can_tho:         'Cần Thơ',
  cao_bang:        'Cao Bằng',
  da_nang:         'Đà Nẵng',
  dak_lak:         'Đắk Lắk',
  dak_nong:        'Đắk Nông',
  dien_bien:       'Điện Biên',
  dong_nai:        'Đồng Nai',
  dong_thap:       'Đồng Tháp',
  gia_lai:         'Gia Lai',
  ha_giang:        'Hà Giang',
  ha_nam:          'Hà Nam',
  ha_noi:          'Hà Nội',
  ha_tinh:         'Hà Tĩnh',
  hai_duong:       'Hải Dương',
  hai_phong:       'Hải Phòng',
  hau_giang:       'Hậu Giang',
  hoa_binh:        'Hòa Bình',
  hung_yen:        'Hưng Yên',
  khanh_hoa:       'Khánh Hòa',
  kien_giang:      'Kiên Giang',
  kon_tum:         'Kon Tum',
  lai_chau:        'Lai Châu',
  lam_dong:        'Lâm Đồng',
  lang_son:        'Lạng Sơn',
  lao_cai:         'Lào Cai',
  long_an:         'Long An',
  nam_dinh:        'Nam Định',
  nghe_an:         'Nghệ An',
  ninh_binh:       'Ninh Bình',
  ninh_thuan:      'Ninh Thuận',
  phu_tho:         'Phú Thọ',
  phu_yen:         'Phú Yên',
  quang_binh:      'Quảng Bình',
  quang_nam:       'Quảng Nam',
  quang_ngai:      'Quảng Ngãi',
  quang_ninh:      'Quảng Ninh',
  quang_tri:       'Quảng Trị',
  soc_trang:       'Sóc Trăng',
  son_la:          'Sơn La',
  tay_ninh:        'Tây Ninh',
  thai_binh:       'Thái Bình',
  thai_nguyen:     'Thái Nguyên',
  thanh_hoa:       'Thanh Hóa',
  thua_thien_hue:  'Thừa Thiên Huế',
  tien_giang:      'Tiền Giang',
  tp_hcm:          'TP. Hồ Chí Minh',
  tra_vinh:        'Trà Vinh',
  tuyen_quang:     'Tuyên Quang',
  vinh_long:       'Vĩnh Long',
  vinh_phuc:       'Vĩnh Phúc',
  yen_bai:         'Yên Bái',
};

// ─── Trạng thái ứng dụng ────────────────────────────────────────────────────

const state = {
  activeTab:      'pending',   // tab ticket: 'pending' | 'answered'
  alertTab:       'active',    // tab alert: 'overview' | 'active' | 'history' — mặc định gọn để không che khu ticket
  historyPage:    0,
  analyticsYear: null,
  tickets:        [],
  selectedId:     null,
  refreshTimer:   null,
};

// ─── Helpers localStorage ────────────────────────────────────────────────────

function getToken() {
  return localStorage.getItem('officer_token') || '';
}

function getOfficerName() {
  return localStorage.getItem('officer_name') || '';
}

function setOfficerName(val) {
  localStorage.setItem('officer_name', val);
}

// ─── Helpers hiển thị ───────────────────────────────────────────────────────

function regionName(code) {
  if (!code) return '—';
  return REGION_NAMES[code] || code;
}

function formatVNDateTime(isoUtc) {
  if (!isoUtc) return '—';
  try {
    const d = new Date(isoUtc);
    if (isNaN(d.getTime())) return isoUtc;
    return d.toLocaleString('vi-VN', {
      timeZone: 'Asia/Ho_Chi_Minh',
      day:      '2-digit',
      month:    '2-digit',
      year:     'numeric',
      hour:     '2-digit',
      minute:   '2-digit',
    });
  } catch (_) {
    return isoUtc;
  }
}

// Chỉ ngày (không giờ) — dùng cho dải lịch sử. Giữ năm vì lịch sử có thể dài.
function formatVNDate(isoUtc) {
  if (!isoUtc) return '?';
  try {
    const d = new Date(isoUtc);
    if (isNaN(d.getTime())) return isoUtc;
    return d.toLocaleDateString('vi-VN', {
      timeZone: 'Asia/Ho_Chi_Minh',
      day:      '2-digit',
      month:    '2-digit',
      year:     '2-digit',
    });
  } catch (_) {
    return isoUtc;
  }
}

function notifiedViaLabel(via) {
  if (!via || via === 'none') return 'Chưa gửi thông báo';
  const map = { email: 'Email', zalo: 'Zalo OA' };
  return via.split(',').map(function (k) { return map[k.trim()] || k.trim(); }).join(', ');
}

// ─── Fetch có token ──────────────────────────────────────────────────────────

async function apiFetch(path, options) {
  const opts    = options || {};
  const token   = getToken();
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  if (token) headers['X-Officer-Token'] = token;
  return fetch(path, Object.assign({}, opts, { headers }));
}

// ─── Tải dữ liệu từ API ──────────────────────────────────────────────────────

async function loadAlerts() {
  try {
    const yearQuery = state.analyticsYear ? '?year=' + encodeURIComponent(state.analyticsYear) : '';
    const res = await apiFetch('/api/officer/alerts' + yearQuery);
    if (!res.ok) return;
    // Truyền toàn bộ data — hàm render tự xử lý alerts + history
    const data = await res.json();
    renderAlerts(data);
  } catch (_) {
    // Lỗi mạng — giữ nguyên nội dung hiện tại
  }
}

async function loadTickets() {
  try {
    const res = await apiFetch('/api/officer/tickets?status=all');
    if (!res.ok) return;
    const data = await res.json();
    state.tickets = data.tickets || [];
    renderTicketList();
  } catch (_) {
    // Lỗi mạng — giữ nguyên danh sách hiện tại
  }
}

// ─── Render: alert strip ─────────────────────────────────────────────────────

/*
  Phòng thủ: nếu response chưa có field "history" (backend cũ) thì
  chỉ hiện tab "Đang diễn ra", không hiện tab lịch sử, không vỡ.
*/
function renderAlerts(data) {
  const alerts  = (data && Array.isArray(data.alerts)) ? data.alerts : [];
  // history = null khi field vắng mặt (backend chưa deploy)
  const history = (data && Array.isArray(data.history)) ? data.history : null;
  const overview = (data && data.overview && typeof data.overview === 'object')
    ? data.overview
    : null;

  const strip = document.getElementById('alert-strip');
  while (strip.firstChild) strip.removeChild(strip.firstChild);

  if (history === null && state.alertTab === 'history') {
    state.alertTab = 'active';
  }
  if (overview === null && state.alertTab === 'overview') {
    state.alertTab = 'active';
  }
  if (overview && overview.year) {
    state.analyticsYear = overview.year;
  }
  if (history !== null) {
    const lastPage = Math.max(0, Math.ceil(history.length / HISTORY_PAGE_SIZE) - 1);
    state.historyPage = Math.min(state.historyPage, lastPage);
  }
  strip.classList.toggle(
    'alert-strip--history',
    state.alertTab === 'history' && history !== null && history.length > 0
  );
  strip.classList.toggle('alert-strip--overview', state.alertTab === 'overview' && overview !== null);

  // Chỉ hiện tab bar khi backend đã trả về field history
  if (history !== null) {
    const tabBar = buildAlertTabBar(alerts.length, history.length, overview);
    strip.appendChild(tabBar);
  }

  // Panel tổng quan theo năm (backend mới)
  if (overview !== null) {
    const overviewPanel = document.createElement('div');
    overviewPanel.className = 'alert-panel overview-panel';
    overviewPanel.id = 'alert-panel-overview';
    overviewPanel.setAttribute('role', 'tabpanel');
    overviewPanel.setAttribute('aria-labelledby', 'alert-tab-overview');
    overviewPanel.dataset.alertPanel = 'overview';
    if (state.alertTab !== 'overview') overviewPanel.hidden = true;
    buildOverviewPanel(overview, overviewPanel);
    strip.appendChild(overviewPanel);
  }

  // Panel "Đang diễn ra"
  const activePanel = document.createElement('div');
  activePanel.className = 'alert-panel';
  activePanel.id = 'alert-panel-active';
  activePanel.setAttribute('role', 'tabpanel');
  activePanel.setAttribute('aria-labelledby', 'alert-tab-active');
  activePanel.dataset.alertPanel = 'active';
  if (state.alertTab !== 'active') activePanel.hidden = true;
  buildActiveAlertsPanel(alerts, activePanel);
  strip.appendChild(activePanel);

  // Panel "Lịch sử" (chỉ khi field history có)
  if (history !== null) {
    const histPanel = document.createElement('div');
    histPanel.className = 'alert-panel alert-panel--history';
    histPanel.id = 'alert-panel-history';
    histPanel.setAttribute('role', 'tabpanel');
    histPanel.setAttribute('aria-labelledby', 'alert-tab-history');
    histPanel.dataset.alertPanel = 'history';
    if (state.alertTab !== 'history') histPanel.hidden = true;
    buildHistoryPanel(history, histPanel);
    strip.appendChild(histPanel);
  }
}

function buildAlertTabBar(activeCount, historyCount, overview) {
  const bar = document.createElement('div');
  bar.className = 'alert-tab-bar';

  const heading = document.createElement('div');
  heading.className = 'alert-heading';

  const headingDot = document.createElement('span');
  headingDot.className = 'alert-heading-dot';
  headingDot.setAttribute('aria-hidden', 'true');

  const headingText = document.createElement('span');
  headingText.className = 'alert-heading-text';
  headingText.textContent = 'Theo dõi vùng dịch';

  heading.appendChild(headingDot);
  heading.appendChild(headingText);
  bar.appendChild(heading);

  const tabs = document.createElement('div');
  tabs.className = 'alert-tabs';
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'Cảnh báo vùng dịch');

  function makeAlertTab(tabId, label, count, isYear) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'alert-tab-btn' + (state.alertTab === tabId ? ' alert-tab-btn--active' : '');
    btn.id = 'alert-tab-' + tabId;
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-controls', 'alert-panel-' + tabId);
    btn.setAttribute('aria-selected', state.alertTab === tabId ? 'true' : 'false');
    btn.tabIndex = state.alertTab === tabId ? 0 : -1;
    btn.dataset.alertTab = tabId;

    const labelNode = document.createTextNode(label + ' ');
    const countEl   = document.createElement('span');
    countEl.className = 'alert-tab-count' + (isYear ? ' alert-tab-year' : '');
    countEl.textContent = String(count);

    btn.appendChild(labelNode);
    btn.appendChild(countEl);

    btn.addEventListener('click', function () {
      state.alertTab = tabId;
      state.historyPage = tabId === 'history' ? state.historyPage : 0;
      // Cập nhật active trên các nút trong tab bar này
      bar.querySelectorAll('.alert-tab-btn').forEach(function (b) {
        const isSelected = b.dataset.alertTab === tabId;
        b.classList.toggle('alert-tab-btn--active', isSelected);
        b.setAttribute('aria-selected', isSelected ? 'true' : 'false');
        b.tabIndex = isSelected ? 0 : -1;
      });
      // Hiện/ẩn panel tương ứng
      const strip = document.getElementById('alert-strip');
      strip.classList.toggle('alert-strip--history', tabId === 'history' && historyCount > 0);
      strip.classList.toggle('alert-strip--overview', tabId === 'overview' && overview !== null);
      strip.querySelectorAll('.alert-panel').forEach(function (panel) {
        panel.hidden = panel.dataset.alertPanel !== tabId;
      });
    });

    return btn;
  }

  if (overview !== null) {
    tabs.appendChild(makeAlertTab('overview', 'Tổng quan', overview.year || 'Năm', true));
  }
  tabs.appendChild(makeAlertTab('active',  'Đang diễn ra', activeCount, false));
  tabs.appendChild(makeAlertTab('history', 'Lịch sử',      historyCount, false));
  bar.appendChild(tabs);

  return bar;
}

function formatCompactNumber(value) {
  const number = Number(value) || 0;
  return number.toLocaleString('vi-VN');
}

function buildOverviewPanel(overview, container) {
  const toolbar = document.createElement('div');
  toolbar.className = 'overview-toolbar';

  const summary = document.createElement('p');
  summary.className = 'overview-summary';
  summary.textContent = formatCompactNumber(overview.total_questions) + ' câu hỏi · '
    + formatCompactNumber(overview.disease_report_count) + ' phản ánh dịch hại';
  toolbar.appendChild(summary);

  const yearField = document.createElement('label');
  yearField.className = 'overview-year-field';

  const yearLabel = document.createElement('span');
  yearLabel.textContent = 'Năm';

  const yearSelect = document.createElement('select');
  yearSelect.className = 'overview-year-select';
  yearSelect.setAttribute('aria-label', 'Chọn năm thống kê');

  const years = Array.isArray(overview.available_years) && overview.available_years.length
    ? overview.available_years
    : [overview.year];
  years.forEach(function (year) {
    const option = document.createElement('option');
    option.value = String(year);
    option.textContent = String(year);
    option.selected = Number(year) === Number(overview.year);
    yearSelect.appendChild(option);
  });

  yearSelect.addEventListener('change', function () {
    const selectedYear = Number(yearSelect.value);
    if (!selectedYear || selectedYear === Number(state.analyticsYear)) return;
    state.analyticsYear = selectedYear;
    setRefreshStatus('Đang tải số liệu năm ' + selectedYear + '…');
    loadAlerts();
  });

  yearField.appendChild(yearLabel);
  yearField.appendChild(yearSelect);
  toolbar.appendChild(yearField);
  container.appendChild(toolbar);

  const grid = document.createElement('div');
  grid.className = 'overview-grid';
  grid.appendChild(buildRegionRanking(
    'Phản ánh dịch hại theo vùng',
    'Vùng có nhiều câu hỏi liên quan dịch hại nhất',
    overview.disease_reports_by_region || [],
    'disease_report_count',
    'phản ánh',
    true
  ));
  grid.appendChild(buildRegionRanking(
    'Nguồn câu hỏi theo vùng',
    'Vùng gửi nhiều câu hỏi đến hệ thống nhất',
    overview.questions_by_region || [],
    'question_count',
    'câu hỏi',
    false
  ));
  container.appendChild(grid);

  const note = document.createElement('p');
  note.className = 'overview-note';
  note.textContent = overview.note
    || 'Số liệu dịch hại dựa trên câu hỏi người dùng, không phải thống kê dịch đã xác minh.';
  container.appendChild(note);
}

function buildRegionRanking(title, description, items, countField, unit, showOutbreaks) {
  const card = document.createElement('section');
  card.className = 'overview-card';

  const header = document.createElement('div');
  header.className = 'overview-card-header';

  const heading = document.createElement('h3');
  heading.className = 'overview-card-title';
  heading.textContent = title;

  const caption = document.createElement('p');
  caption.className = 'overview-card-caption';
  caption.textContent = description;

  header.appendChild(heading);
  header.appendChild(caption);
  card.appendChild(header);

  if (!items.length) {
    const empty = document.createElement('p');
    empty.className = 'overview-empty';
    empty.textContent = 'Chưa có dữ liệu vùng trong năm này.';
    card.appendChild(empty);
    return card;
  }

  const list = document.createElement('div');
  list.className = 'overview-rank-list';
  list.setAttribute('role', 'list');
  const maxValue = Number(items[0][countField]) || 1;

  items.slice(0, 5).forEach(function (item, index) {
    const value = Number(item[countField]) || 0;
    const row = document.createElement('div');
    row.className = 'overview-rank-row' + (index === 0 ? ' overview-rank-row--top' : '');
    row.setAttribute('role', 'listitem');

    const rank = document.createElement('span');
    rank.className = 'overview-rank-number';
    rank.textContent = String(index + 1);

    const region = document.createElement('div');
    region.className = 'overview-rank-region';

    const regionLabel = document.createElement('span');
    regionLabel.className = 'overview-rank-name';
    regionLabel.textContent = item.region_name || regionName(item.region);
    region.appendChild(regionLabel);

    if (showOutbreaks && Number(item.outbreak_count) > 0) {
      const outbreaks = document.createElement('span');
      outbreaks.className = 'overview-rank-sub';
      outbreaks.textContent = formatCompactNumber(item.outbreak_count) + ' đợt cảnh báo';
      region.appendChild(outbreaks);
    }

    const bar = document.createElement('span');
    bar.className = 'overview-rank-bar';
    bar.setAttribute('aria-hidden', 'true');
    const fill = document.createElement('span');
    fill.className = 'overview-rank-fill';
    fill.style.width = Math.max(4, Math.round((value / maxValue) * 100)) + '%';
    bar.appendChild(fill);

    const valueEl = document.createElement('span');
    valueEl.className = 'overview-rank-value';
    valueEl.textContent = formatCompactNumber(value) + ' ' + unit;

    row.appendChild(rank);
    row.appendChild(region);
    row.appendChild(bar);
    row.appendChild(valueEl);
    list.appendChild(row);
  });

  card.appendChild(list);
  return card;
}

function buildActiveAlertsPanel(alerts, container) {
  if (!alerts || alerts.length === 0) {
    const row = document.createElement('div');
    row.className = 'alert-ok';
    const dot = document.createElement('span');
    dot.className = 'alert-ok-dot';
    dot.setAttribute('aria-hidden', 'true');
    const msg = document.createElement('span');
    msg.textContent = 'Chưa ghi nhận điểm nóng dịch hại trong 7 ngày qua';
    row.appendChild(dot);
    row.appendChild(msg);
    container.appendChild(row);
    return;
  }

  alerts.forEach(function (alert, alertIndex) {
    const count      = alert.count || 0;
    const isHigh     = count >= 10;
    const hasSamples = alert.sample_questions && alert.sample_questions.length > 0;

    const row = document.createElement('div');
    row.className = isHigh ? 'alert-row alert-row--high' : 'alert-row';

    const main = document.createElement('div');
    main.className = 'alert-main';

    const countEl = document.createElement('span');
    countEl.className = 'alert-count';
    countEl.textContent = String(count);

    const regionEl = document.createElement('span');
    regionEl.className = 'alert-region';
    regionEl.textContent = regionName(alert.region);

    const sep = document.createElement('span');
    sep.className = 'alert-separator';
    sep.setAttribute('aria-hidden', 'true');
    sep.textContent = '—';

    const infoEl = document.createElement('span');
    infoEl.className = 'alert-em';
    infoEl.textContent = 'câu hỏi về ' + (alert.topic || '?');
    infoEl.title = infoEl.textContent;

    const periodEl = document.createElement('span');
    periodEl.className = 'alert-period';
    periodEl.textContent = '/ 7 ngày';

    const toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'alert-toggle';
    toggleBtn.textContent = 'xem mẫu';
    toggleBtn.setAttribute('aria-expanded', 'false');
    if (!hasSamples) toggleBtn.disabled = true;

    main.appendChild(countEl);
    main.appendChild(regionEl);
    main.appendChild(sep);
    main.appendChild(infoEl);
    main.appendChild(periodEl);
    main.appendChild(toggleBtn);
    row.appendChild(main);

    if (hasSamples) {
      const samplesEl = document.createElement('div');
      samplesEl.className = 'alert-samples';
      samplesEl.id = 'alert-samples-' + alertIndex;
      samplesEl.setAttribute('role', 'region');
      samplesEl.setAttribute('aria-label', 'Câu hỏi mẫu tại ' + regionName(alert.region));
      samplesEl.hidden = true;
      toggleBtn.setAttribute('aria-controls', samplesEl.id);

      alert.sample_questions.forEach(function (q) {
        const item = document.createElement('div');
        item.className = 'alert-sample-item';
        item.textContent = q;
        samplesEl.appendChild(item);
      });

      row.appendChild(samplesEl);

      toggleBtn.addEventListener('click', function () {
        const expanded = !samplesEl.hidden;
        samplesEl.hidden = expanded;
        toggleBtn.textContent = expanded ? 'xem mẫu' : 'ẩn';
        toggleBtn.setAttribute('aria-expanded', String(!expanded));
      });
    }

    container.appendChild(row);
  });
}

function buildHistoryPanel(history, container) {
  while (container.firstChild) container.removeChild(container.firstChild);

  if (!history || history.length === 0) {
    const row = document.createElement('div');
    row.className = 'alert-ok';
    const dot = document.createElement('span');
    dot.className = 'alert-ok-dot';
    dot.setAttribute('aria-hidden', 'true');
    const msg = document.createElement('span');
    msg.textContent = 'Chưa có dữ liệu lịch sử dịch hại.';
    row.appendChild(dot);
    row.appendChild(msg);
    container.appendChild(row);
    return;
  }

  const pageCount = Math.max(1, Math.ceil(history.length / HISTORY_PAGE_SIZE));
  state.historyPage = Math.min(Math.max(0, state.historyPage), pageCount - 1);
  const startIndex = state.historyPage * HISTORY_PAGE_SIZE;
  const pageItems = history.slice(startIndex, startIndex + HISTORY_PAGE_SIZE);

  const toolbar = document.createElement('div');
  toolbar.className = 'history-toolbar';

  const summary = document.createElement('span');
  summary.className = 'history-summary';
  summary.textContent = history.length + ' đợt được ghi nhận';

  const order = document.createElement('span');
  order.className = 'history-order';
  order.textContent = 'Mới cập nhật trước';

  toolbar.appendChild(summary);
  toolbar.appendChild(order);
  container.appendChild(toolbar);

  const list = document.createElement('div');
  list.className = 'history-list';
  list.setAttribute('role', 'list');

  pageItems.forEach(function (item) {
    // Ưu tiên region_name từ server; fallback sang lookup code
    const displayRegion = item.region_name || regionName(item.region);

    const row = document.createElement('div');
    row.className = item.active ? 'history-row history-row--active' : 'history-row';
    row.setAttribute('role', 'listitem');

    const eventEl = document.createElement('div');
    eventEl.className = 'history-event';

    const regionEl = document.createElement('span');
    regionEl.className = 'history-region';
    regionEl.textContent = displayRegion;

    const topicEl = document.createElement('span');
    topicEl.className = 'history-topic';
    topicEl.textContent = item.topic || '—';

    const rangeEl = document.createElement('span');
    rangeEl.className = 'history-range';
    rangeEl.textContent = formatVNDate(item.first_ts) + ' – ' + formatVNDate(item.last_ts);
    rangeEl.title = 'Từ ' + formatVNDateTime(item.first_ts) + ' đến ' + formatVNDateTime(item.last_ts);

    const peakEl = document.createElement('span');
    peakEl.className = 'history-peak';
    peakEl.textContent = 'Đỉnh ' + (item.peak_count || 0) + ' câu';

    const badge = document.createElement('span');
    badge.className = item.active
      ? 'history-badge history-badge--active'
      : 'history-badge history-badge--dormant';
    badge.textContent = item.active ? 'Đang diễn ra' : 'Đã lắng';

    eventEl.appendChild(regionEl);
    eventEl.appendChild(topicEl);
    row.appendChild(eventEl);
    row.appendChild(rangeEl);
    row.appendChild(peakEl);
    row.appendChild(badge);

    list.appendChild(row);
  });

  container.appendChild(list);

  const pagination = document.createElement('div');
  pagination.className = 'history-pagination';
  pagination.setAttribute('aria-label', 'Phân trang lịch sử cảnh báo');

  const rangeLabel = document.createElement('span');
  rangeLabel.className = 'history-page-range';
  rangeLabel.textContent = (startIndex + 1) + '–' + (startIndex + pageItems.length) + ' / ' + history.length;

  const pageStatus = document.createElement('span');
  pageStatus.className = 'history-page-status';
  pageStatus.textContent = 'Trang ' + (state.historyPage + 1) + ' / ' + pageCount;
  pageStatus.setAttribute('aria-live', 'polite');

  const actions = document.createElement('div');
  actions.className = 'history-page-actions';

  function makePageButton(label, delta, disabled) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-page-btn';
    button.textContent = label;
    button.disabled = disabled;
    button.addEventListener('click', function () {
      state.historyPage += delta;
      buildHistoryPanel(history, container);
    });
    return button;
  }

  actions.appendChild(makePageButton('Trước', -1, state.historyPage === 0));
  actions.appendChild(makePageButton('Sau', 1, state.historyPage >= pageCount - 1));

  pagination.appendChild(rangeLabel);
  pagination.appendChild(pageStatus);
  pagination.appendChild(actions);
  container.appendChild(pagination);
}

// ─── Render: danh sách ticket ────────────────────────────────────────────────

function renderTicketList() {
  const list     = document.getElementById('ticket-list');
  const pending  = state.tickets.filter(function (t) { return t.status === 'pending'; });
  const answered = state.tickets.filter(function (t) { return t.status === 'answered'; });

  document.getElementById('count-pending').textContent  = String(pending.length);
  document.getElementById('count-answered').textContent = String(answered.length);

  const visible = state.activeTab === 'pending' ? pending : answered;

  while (list.firstChild) list.removeChild(list.firstChild);

  if (visible.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'ticket-empty';
    empty.textContent = state.activeTab === 'pending'
      ? 'Không có câu hỏi nào đang chờ trả lời.'
      : 'Chưa có câu hỏi nào đã được trả lời.';
    list.appendChild(empty);
    return;
  }

  visible.forEach(function (ticket) {
    const isActive = ticket.ticket_id === state.selectedId;

    const row = document.createElement('div');
    row.className = 'ticket-row' + (isActive ? ' ticket-row--active' : '');
    row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', isActive ? 'true' : 'false');
    row.dataset.id = String(ticket.ticket_id);

    const meta = document.createElement('div');
    meta.className = 'ticket-meta';

    const timeEl = document.createElement('span');
    timeEl.className = 'ticket-time';
    timeEl.textContent = formatVNDateTime(ticket.ts);

    const regionEl = document.createElement('span');
    regionEl.className = 'ticket-region-badge';
    regionEl.textContent = regionName(ticket.region);

    meta.appendChild(timeEl);
    meta.appendChild(regionEl);

    const cropEl = document.createElement('div');
    cropEl.className = 'ticket-crop';
    const cropParts = [ticket.crop, ticket.pest].filter(Boolean);
    cropEl.textContent = cropParts.length ? cropParts.join(' · ') : '—';

    const qEl = document.createElement('div');
    qEl.className = 'ticket-question-preview';
    const qText = ticket.question || ticket.transcript || '';
    qEl.textContent = qText.length > 100 ? qText.slice(0, 100) + '…' : qText;

    row.appendChild(meta);
    row.appendChild(cropEl);
    row.appendChild(qEl);

    row.addEventListener('click', function () {
      selectTicket(ticket.ticket_id);
    });

    list.appendChild(row);
  });
}

// ─── Chọn ticket ────────────────────────────────────────────────────────────

function selectTicket(id) {
  state.selectedId = id;
  renderTicketList();
  renderDetail();
}

// ─── Render: panel chi tiết ──────────────────────────────────────────────────

function renderDetail() {
  const pane      = document.getElementById('detail-pane');
  const emptyEl   = document.getElementById('empty-state');
  const oldDetail = pane.querySelector('.ticket-detail');

  if (!state.selectedId) {
    emptyEl.hidden = false;
    if (oldDetail) oldDetail.remove();
    return;
  }

  const ticket = state.tickets.find(function (t) { return t.ticket_id === state.selectedId; });
  if (!ticket) {
    state.selectedId = null;
    emptyEl.hidden = false;
    if (oldDetail) oldDetail.remove();
    return;
  }

  emptyEl.hidden = true;
  if (oldDetail) oldDetail.remove();

  const detail = buildDetailEl(ticket);
  pane.appendChild(detail);
}

function buildDetailEl(ticket) {
  const el = document.createElement('div');
  el.className = 'ticket-detail';

  // --- Header ---
  const hdr = document.createElement('div');
  hdr.className = 'detail-header';

  const hdrLeft = document.createElement('div');
  hdrLeft.className = 'detail-header-left';

  const titleEl = document.createElement('h2');
  titleEl.className = 'detail-title';

  const titleText = document.createTextNode('Câu hỏi #' + ticket.ticket_id + ' ');
  const badge = document.createElement('span');
  badge.className = ticket.status === 'pending' ? 'badge badge--pending' : 'badge badge--answered';
  badge.textContent = ticket.status === 'pending' ? 'Chờ trả lời' : 'Đã trả lời';

  titleEl.appendChild(titleText);
  titleEl.appendChild(badge);
  hdrLeft.appendChild(titleEl);
  hdr.appendChild(hdrLeft);
  el.appendChild(hdr);

  // --- Thông tin ticket ---
  const infoSection = document.createElement('div');
  infoSection.className = 'detail-info';

  const question   = ticket.question || ticket.transcript || '';
  const transcript = ticket.transcript || '';

  addInfoRow(infoSection, 'Câu hỏi',    question);

  if (transcript && transcript !== question && transcript.trim()) {
    addInfoRow(infoSection, 'Transcript gốc', transcript);
  }

  addInfoRow(infoSection, 'Vùng',      regionName(ticket.region));
  addInfoRow(infoSection, 'Cây trồng', ticket.crop || '—');
  addInfoRow(infoSection, 'Dịch hại',  ticket.pest || '—');
  addInfoRow(infoSection, 'Thời gian', formatVNDateTime(ticket.ts));
  addInfoRow(infoSection, 'Người hỏi', ticket.contact_name || '—');

  const contact = [ticket.contact_phone, ticket.contact_email].filter(Boolean).join(' · ');
  addInfoRow(infoSection, 'Liên hệ',   contact || '—');

  if (ticket.status === 'answered') {
    const sep = document.createElement('hr');
    sep.className = 'detail-section-sep';
    infoSection.appendChild(sep);

    addInfoRow(infoSection, 'Câu trả lời',    ticket.answer      || '—');
    addInfoRow(infoSection, 'Cán bộ trả lời', ticket.answered_by || '—');
    addInfoRow(infoSection, 'Trả lời lúc',    formatVNDateTime(ticket.answered_at));
    addInfoRow(infoSection, 'Thông báo qua',  notifiedViaLabel(ticket.notified_via));
  }

  el.appendChild(infoSection);

  if (ticket.status === 'pending') {
    el.appendChild(buildAnswerForm(ticket.ticket_id));
  }

  return el;
}

function addInfoRow(parent, label, value) {
  const row = document.createElement('div');
  row.className = 'info-row';

  const lbl = document.createElement('dt');
  lbl.className = 'info-label';
  lbl.textContent = label;

  const val = document.createElement('dd');
  val.className = 'info-value';
  val.textContent = value;

  row.appendChild(lbl);
  row.appendChild(val);
  parent.appendChild(row);
}

// ─── Form trả lời ────────────────────────────────────────────────────────────

function buildAnswerForm(ticketId) {
  const form = document.createElement('div');
  form.className = 'answer-form';

  const formTitle = document.createElement('div');
  formTitle.className = 'form-title';
  formTitle.textContent = 'Gửi câu trả lời';
  form.appendChild(formTitle);

  // Tên cán bộ
  const nameGroup = document.createElement('div');
  nameGroup.className = 'form-group';

  const nameLabel = document.createElement('label');
  nameLabel.className = 'form-label';
  nameLabel.textContent = 'Tên cán bộ';
  nameLabel.htmlFor = 'officer-name-input';

  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.id = 'officer-name-input';
  nameInput.className = 'form-input';
  nameInput.value = getOfficerName();
  nameInput.placeholder = 'Nhập họ tên cán bộ trả lời';
  nameInput.autocomplete = 'name';
  nameInput.addEventListener('input', function () {
    setOfficerName(nameInput.value);
  });

  nameGroup.appendChild(nameLabel);
  nameGroup.appendChild(nameInput);

  // Nội dung trả lời
  const ansGroup = document.createElement('div');
  ansGroup.className = 'form-group';

  const ansLabel = document.createElement('label');
  ansLabel.className = 'form-label';
  ansLabel.textContent = 'Nội dung trả lời';
  ansLabel.htmlFor = 'officer-answer-input';

  const answerEl = document.createElement('textarea');
  answerEl.id = 'officer-answer-input';
  answerEl.className = 'form-textarea';
  answerEl.rows = 6;
  answerEl.placeholder = 'Nhập nội dung trả lời rõ ràng, dễ hiểu cho bà con…';

  ansGroup.appendChild(ansLabel);
  ansGroup.appendChild(answerEl);

  // Nút gửi
  const actionsDiv = document.createElement('div');
  actionsDiv.className = 'form-actions';

  const submitBtn = document.createElement('button');
  submitBtn.type = 'button';
  submitBtn.className = 'btn-primary';
  submitBtn.textContent = 'Gửi trả lời';

  submitBtn.addEventListener('click', function () {
    const answer      = answerEl.value.trim();
    const officerName = nameInput.value.trim();

    if (!answer) {
      showToast('Vui lòng nhập nội dung trả lời trước khi gửi.', 'error');
      answerEl.focus();
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Đang gửi…';

    postAnswer(ticketId, answer, officerName, submitBtn);
  });

  actionsDiv.appendChild(submitBtn);

  form.appendChild(nameGroup);
  form.appendChild(ansGroup);
  form.appendChild(actionsDiv);

  return form;
}

// ─── Gửi câu trả lời ─────────────────────────────────────────────────────────

async function postAnswer(ticketId, answer, officerName, submitBtn) {
  try {
    const res = await apiFetch('/api/officer/tickets/' + ticketId + '/answer', {
      method: 'POST',
      body:   JSON.stringify({ answer: answer, officer_name: officerName }),
    });

    if (res.status === 409) {
      showToast('Câu hỏi này đã được trả lời rồi.', 'error');
      restoreBtn(submitBtn);
      return;
    }

    if (res.status === 401) {
      showToast('Xác thực thất bại. Vui lòng kiểm tra lại mã token cán bộ.', 'error');
      restoreBtn(submitBtn);
      return;
    }

    if (!res.ok) {
      showToast('Gửi không thành công (lỗi ' + res.status + '). Vui lòng thử lại.', 'error');
      restoreBtn(submitBtn);
      return;
    }

    const data = await res.json();
    const via  = data.notified_via || 'none';

    var viaMsg;
    if (via === 'none' || !via) {
      viaMsg = 'Bà con sẽ thấy câu trả lời trong app.';
    } else {
      const labels = via.split(',').map(function (k) {
        const kk = k.trim();
        if (kk === 'email') return 'email';
        if (kk === 'zalo')  return 'Zalo';
        return kk;
      }).join(' và ');
      viaMsg = 'Đã báo cho bà con qua ' + labels + '.';
    }

    showToast('Đã gửi trả lời thành công. ' + viaMsg, 'success');

    await loadTickets();
    switchTab('answered');

  } catch (_) {
    showToast('Lỗi kết nối mạng. Vui lòng kiểm tra kết nối và thử lại.', 'error');
    restoreBtn(submitBtn);
  }
}

function restoreBtn(btn) {
  if (!btn) return;
  btn.disabled = false;
  btn.textContent = 'Gửi trả lời';
}

// ─── Toast ───────────────────────────────────────────────────────────────────

function showToast(msg, type) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast toast--' + (type || 'info');
  toast.textContent = msg;
  toast.setAttribute('role', 'status');

  container.appendChild(toast);

  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      toast.classList.add('toast--visible');
    });
  });

  setTimeout(function () {
    toast.classList.remove('toast--visible');
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, TOAST_FADE_MS);
  }, TOAST_DURATION_MS);
}

// ─── Chuyển tab ticket ───────────────────────────────────────────────────────

/*
  Lưu ý: chỉ tác động đến .tab-btn (ticket tabs) — không liên quan
  đến .alert-tab-btn (alert tabs). Hai class khác nhau, không xung đột.
*/
function switchTab(tab) {
  state.activeTab = tab;

  document.querySelectorAll('.tab-btn').forEach(function (btn) {
    const isActive = btn.dataset.tab === tab;
    btn.classList.toggle('tab-btn--active', isActive);
    btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
  });

  renderTicketList();
}

// ─── Refresh toàn bộ ─────────────────────────────────────────────────────────

async function refreshAll() {
  setRefreshStatus('Đang làm mới…');
  await Promise.all([loadAlerts(), loadTickets()]);

  if (state.selectedId) {
    const found = state.tickets.find(function (t) { return t.ticket_id === state.selectedId; });
    if (found) {
      renderDetail();
    } else {
      state.selectedId = null;
      renderDetail();
    }
  }

  setRefreshStatus('Cập nhật ' + new Date().toLocaleTimeString('vi-VN', {
    timeZone: 'Asia/Ho_Chi_Minh',
    hour:     '2-digit',
    minute:   '2-digit',
  }));
}

function setRefreshStatus(msg) {
  const el = document.getElementById('refresh-status');
  if (el) el.textContent = msg;
}

// ─── Khởi tạo ────────────────────────────────────────────────────────────────

function init() {
  document.querySelectorAll('.tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      switchTab(btn.dataset.tab);
    });
  });

  const refreshBtn = document.getElementById('btn-refresh');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', function () {
      refreshAll();
    });
  }

  refreshAll();

  state.refreshTimer = setInterval(refreshAll, REFRESH_INTERVAL_MS);
}

document.addEventListener('DOMContentLoaded', init);
