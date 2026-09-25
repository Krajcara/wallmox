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
    clockEl.innerHTML = pad(d.getHours()) + ':' + pad(d.getMinutes());
    dateEl.innerHTML = days[d.getDay()] + ' ' + pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.';
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
