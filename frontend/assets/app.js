const map = L.map('map').setView([1.3, 103.8], 3);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const form = document.querySelector('#lookup-form');
const input = document.querySelector('#imo');
const message = document.querySelector('#message');
const result = document.querySelector('#result');
const vesselMarkers = new Map();
let initialFleetView = true;
let selectedMmsi = null;
let fleet = [];
let lookupSequence = 0;
const vesselList = document.querySelector('#vessel-list');
const fleetStatus = document.querySelector('#fleet-status');

const markSelection = () => {
  vesselList.querySelectorAll('button').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.mmsi === selectedMmsi));
  });
};

const renderFleet = () => {
  document.querySelector('#fleet-count').textContent = `(${fleet.length})`;
  fleetStatus.textContent = fleet.length ? 'Select a vessel to view its latest saved position.' : 'No vessels configured.';
  const focusedMmsi = document.activeElement?.dataset?.mmsi;
  vesselList.replaceChildren(...fleet.map(vessel => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'vessel-option';
    button.dataset.mmsi = String(vessel.mmsi);
    button.innerHTML = `<strong>${escapeHtml(vessel.name || vessel.mmsi)}</strong>
      <small>IMO ${escapeHtml(vessel.imo || '?')} ? MMSI ${escapeHtml(vessel.mmsi)}</small>
      <span class="position-status ${vessel.position_available ? '' : 'pending'}">${vessel.position_available ? `Last observation: ${age(vessel.timestamp)}` : 'Waiting for an OpenWaters position'}</span>`;
    button.addEventListener('click', () => {
      lookupSequence++;
      form.querySelector('button').disabled = false;
      input.value = vessel.imo || vessel.mmsi;
      showVessel(vessel, true);
    });
    return button;
  }));
  markSelection();
  if (focusedMmsi) [...vesselList.querySelectorAll('button')].find(b => b.dataset.mmsi === focusedMmsi)?.focus({preventScroll: true});
};

const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));
const display = (value, suffix = '') => value === null || value === undefined || value === '' ? '—' : `${escapeHtml(value)}${suffix}`;
const age = timestamp => {
  if (!timestamp) return 'unknown age';
  const hours = Math.max(0, (Date.now() - new Date(timestamp).getTime()) / 3600000);
  if (hours < 1) return `${Math.round(hours * 60)} minutes ago`;
  if (hours < 48) return `${Math.round(hours)} hours ago`;
  const days = Math.round(hours / 24);
  if (days < 60) return `${days} days ago`;
  const months = Math.round(days / 30.44);
  if (months < 24) return `${months} months ago`;
  return `${(days / 365.25).toFixed(1)} years ago`;
};

const markerPopup = vessel => `
  <b>${escapeHtml(vessel.name || 'Unknown vessel')}</b><br>
  IMO ${escapeHtml(vessel.imo)}<br>
  ${vessel.provider ? `Source: ${escapeHtml(vessel.provider)}<br>` : ''}
  Last seen: ${age(vessel.timestamp || vessel.source_at)}
`;

const vesselIcon = vessel => {
  const course = Number(vessel.course);
  // The SVG points north at 0°, matching the AIS course convention.
  const rotation = Number.isFinite(course) ? course : 0;
  return L.divIcon({
    className: 'vessel-marker',
    html: `<span class="vessel-marker__symbol" style="transform:rotate(${rotation}deg)" aria-hidden="true">
      <svg viewBox="0 0 32 32" focusable="false">
        <path class="vessel-marker__direction" d="M16 2 27 27 16 22 5 27Z"/>
        <path class="vessel-marker__centerline" d="M16 8v12"/>
      </svg>
    </span>`,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    popupAnchor: [0, -20],
    tooltipAnchor: [0, -20],
  });
};

const upsertVesselMarker = (vessel, open = false) => {
  const latitude = vessel.latitude ?? vessel.lat;
  const longitude = vessel.longitude ?? vessel.lon;
  const course = Number(vessel.course);
  if (latitude === null || latitude === undefined || longitude === null || longitude === undefined) return null;

  let vesselMarker = vesselMarkers.get(String(vessel.mmsi));
  if (vesselMarker) {
    vesselMarker.setLatLng([latitude, longitude]);
    vesselMarker.setIcon(vesselIcon(vessel));
  } else {
    vesselMarker = L.marker([latitude, longitude], {
      icon: vesselIcon(vessel),
      title: `${vessel.name || `IMO ${vessel.imo}`} — course ${Number.isFinite(course) ? `${course}°` : 'unknown'}`,
    }).addTo(map);
    vesselMarkers.set(String(vessel.mmsi), vesselMarker);
  }
  vesselMarker.bindTooltip(escapeHtml(vessel.name || `IMO ${vessel.imo}`), { direction: 'top' });
  vesselMarker.bindPopup(markerPopup(vessel));
  if (open) vesselMarker.openPopup();
  return vesselMarker;
};

const showVessel = (data, focusMap = false) => {
  selectedMmsi = String(data.mmsi);
  markSelection();
    message.textContent = data.position_available && data.historical
      ? `Latest saved OpenWaters observation: ${age(data.timestamp)}.`
      : data.position_available ? '' : 'No OpenWaters position has been saved for this vessel yet.';
    message.className = data.historical || !data.position_available ? 'notice' : '';
    result.innerHTML = `
      <div class="result-heading"><div><small>VESSEL FOUND</small><h2>${display(data.name)}</h2></div><span>IMO ${display(data.imo)}</span></div>
      <dl>
        <div><dt>MMSI</dt><dd>${display(data.mmsi)}</dd></div>
        <div><dt>Speed</dt><dd>${display(data.speed, ' kn')}</dd></div>
        <div><dt>Course</dt><dd>${display(data.course, '°')}</dd></div>
        <div><dt>Data source</dt><dd>${display(data.provider)}</dd></div>
        <div><dt>Position time</dt><dd>${data.timestamp ? `${new Date(data.timestamp).toLocaleString()} (${age(data.timestamp)})` : '—'}</dd></div>
      </dl>`;
    result.hidden = false;

    if (data.position_available && focusMap) {
      upsertVesselMarker(data, true);
      map.setView([data.latitude, data.longitude], 9);
      setTimeout(() => map.invalidateSize(), 0);
    }
};

const refreshTrackedVessels = async () => {
  try {
    const response = await fetch('/api/vessels');
    if (!response.ok) throw new Error('Fleet unavailable');
    const vessels = await response.json();
    fleet = vessels;
    renderFleet();
    const selected = fleet.find(v => String(v.mmsi) === selectedMmsi);
    if (selected) showVessel(selected);
    else if (selectedMmsi) { selectedMmsi = null; result.hidden = true; message.textContent = ''; }
    const visibleImos = new Set();
    const bounds = [];

    vessels.forEach(vessel => {
      const vesselMarker = upsertVesselMarker(vessel);
      if (!vesselMarker) return;
      visibleImos.add(String(vessel.mmsi));
      bounds.push(vesselMarker.getLatLng());
    });

    vesselMarkers.forEach((vesselMarker, imo) => {
      if (!visibleImos.has(imo)) {
        vesselMarker.remove();
        vesselMarkers.delete(imo);
      }
    });

    if (initialFleetView && bounds.length) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 9 });
      initialFleetView = false;
    }
  } catch (_) {
    fleetStatus.textContent = 'Unable to refresh vessels. Retrying automatically; saved results remain visible.';
  }
};

refreshTrackedVessels();
setInterval(refreshTrackedVessels, 60_000);

form.addEventListener('submit', async event => {
  event.preventDefault();
  const imo = input.value.trim();
  const requestId = ++lookupSequence;
  message.className = 'loading';
  message.textContent = 'Searching vessel data and latest AIS position…';
  result.hidden = true;
  form.querySelector('button').disabled = true;

  try {
    const response = await fetch(`/api/lookup/${encodeURIComponent(imo)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Vessel lookup failed');

    if (requestId !== lookupSequence) return;
    showVessel(data, true);
  } catch (error) {
    if (requestId !== lookupSequence) return;
    message.className = 'error';
    message.textContent = error.message;
  } finally {
    if (requestId === lookupSequence) form.querySelector('button').disabled = false;
  }
});
