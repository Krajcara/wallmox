/* Wallmox status page updater.
   Plain ES5 on purpose: must run on Android 4.4 browsers. */
(function () {
  var body = document.body;
  var dash = document.getElementById('dash');
  var conn = document.getElementById('conn');
  var clockEl = document.getElementById('clock');
  var dateEl = document.getElementById('date');
  var refreshMs = (parseInt(body.getAttribute('data-refresh'), 10) || 10) * 1000;
  var url = body.getAttribute('data-fragment-url');
  var days = (body.getAttribute('data-days') || 'Sun Mon Tue Wed Thu Fri Sat').split(' ');
  var failures = 0;

  conn.removeAttribute('hidden');
  conn.className = 'conn is-hidden';

  function pad(n) { return n < 10 ? '0' + n : '' + n; }

  function tickClock() {
    var d = new Date();
    if (typeof applyNight === 'function') { applyNight(); }
    clockEl.innerHTML = pad(d.getHours()) + ':' + pad(d.getMinutes());
    dateEl.innerHTML = days[d.getDay()] + ' ' + pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.';
  }

  /* Night mode, evaluated with the tablet's own clock. */
  var nightEl = document.getElementById('night');
  var wakeUntil = 0;

  function toMinutes(t) {
    var p = (t || '').split(':');
    return parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
  }

  function nightConfig() {
    var el = document.getElementById('night-config');
    if (!el) { return { enabled: false }; }
    return {
      enabled: el.getAttribute('data-enabled') === '1',
      start: toMinutes(el.getAttribute('data-start')),
      end: toMinutes(el.getAttribute('data-end')),
      mode: el.getAttribute('data-mode'),
      level: parseInt(el.getAttribute('data-level'), 10) || 20,
      tap: el.getAttribute('data-tap') === '1'
    };
  }

  function isNight(cfg) {
    if (!cfg.enabled || isNaN(cfg.start) || isNaN(cfg.end) || cfg.start === cfg.end) { return false; }
    var d = new Date();
    var now = d.getHours() * 60 + d.getMinutes();
    return cfg.start < cfg.end ? (now >= cfg.start && now < cfg.end)
                               : (now >= cfg.start || now < cfg.end);
  }

  function applyNight() {
    var cfg = nightConfig();
    if (!isNight(cfg) || new Date().getTime() < wakeUntil) {
      nightEl.className = 'night';
      nightEl.style.opacity = '0';
      return;
    }
    var opacity = cfg.mode === 'off' ? 1 : Math.max(0, Math.min(0.95, 1 - cfg.level / 100));
    if (nightEl.className !== 'night is-on') {
      nightEl.className = 'night is-on';
      setTimeout(function () { nightEl.style.opacity = String(opacity); }, 30);
    } else {
      nightEl.style.opacity = String(opacity);
    }
  }

  function wake() {
    var cfg = nightConfig();
    if (cfg.tap && isNight(cfg)) {
      wakeUntil = new Date().getTime() + 60 * 1000;
      applyNight();
    }
  }
  nightEl.addEventListener('click', wake, false);
  nightEl.addEventListener('touchstart', wake, false);

  /* Battery and WiFi of this tablet: sent by its screen helper, rendered by the
     server into #tablet-src; without a helper, use the browser's battery info. */
  var tabletSlot = document.getElementById('tablet');
  var browserBattery = null;

  function batteryHtml(pct, charging) {
    var level = (!charging || pct < 20) ? 'crit' : 'ok';
    return '<span class="tb tb-bat tb-' + level + '"><svg viewBox="0 0 28 14" aria-hidden="true">' +
      '<rect class="bat-body" x="0.8" y="0.8" width="23.4" height="12.4" rx="2.6"/>' +
      '<rect class="bat-nub" x="25" y="4.6" width="2.3" height="4.8" rx="1"/>' +
      '<rect class="bat-fill" x="2.6" y="2.6" width="' + (pct * 19.8 / 100).toFixed(1) + '" height="8.8" rx="1.2"/>' +
      (charging ? '<path class="bat-bolt" d="M13.8 1.6 8.6 7.9h3.6l-1.5 4.5 5.3-6.4h-3.6z"/>' : '') +
      '</svg><span class="tb-text">' + pct + '%' +
      (charging ? '' : ' ' + (body.getAttribute('data-on-battery') || '')) + '</span></span>';
  }

  function showTablet() {
    var src = document.getElementById('tablet-src');
    var html = src ? src.innerHTML.replace(/^\s+|\s+$/g, '') : '';
    /* Browsers without battery information report "100%, charging, fully charged"; skip that. */
    var fake = browserBattery && browserBattery.level === 1 && browserBattery.charging &&
               browserBattery.chargingTime === 0;
    if (!html && browserBattery && !fake) {
      html = batteryHtml(Math.round(browserBattery.level * 100), browserBattery.charging);
    }
    if (tabletSlot.innerHTML !== html) { tabletSlot.innerHTML = html; }
  }

  if (navigator.getBattery) {
    try {
      navigator.getBattery().then(function (bat) {
        browserBattery = bat;
        bat.addEventListener('chargingchange', showTablet, false);
        bat.addEventListener('levelchange', showTablet, false);
        showTablet();
      });
    } catch (e) { /* not available */ }
  }

  function setConnected(ok) {
    conn.className = ok ? 'conn is-hidden' : 'conn';
  }

  function refresh() {
    var xhr = new XMLHttpRequest();
    var sep = url.indexOf('?') === -1 ? '?' : '&';
    var done = false;
    var guard = setTimeout(function () { if (!done) { xhr.abort(); } }, 8000);

    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4 || done) { return; }
      done = true;
      clearTimeout(guard);
      if (xhr.status === 200) {
        dash.innerHTML = xhr.responseText;
        applyNight();
        showTablet();
        failures = 0;
        setConnected(true);
      } else {
        failures += 1;
        if (failures >= 2) { setConnected(false); }
      }
      setTimeout(refresh, refreshMs);
    };
    xhr.open('GET', url + sep + '_=' + new Date().getTime(), true);
    xhr.send();
  }

  tickClock();
  setInterval(tickClock, 1000);
  setTimeout(refresh, refreshMs);

  /* Reload the whole page every 6 hours to keep old browsers from leaking memory. */
  setTimeout(function () { window.location.reload(); }, 6 * 3600 * 1000);
})();
