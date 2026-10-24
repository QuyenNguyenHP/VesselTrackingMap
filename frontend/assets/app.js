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

const upsertVesselMarker = (vessel, open = false) => {
  const latitude = vessel.latitude ?? vessel.lat;
  const longitude = vessel.longitude ?? vessel.lon;
  if (latitude === null || latitude === undefined || longitude === null || longitude === undefined) return null;

  let vesselMarker = vesselMarkers.get(String(vessel.imo));
  if (vesselMarker) {
    vesselMarker.setLatLng([latitude, longitude]);
  } else {
    vesselMarker = L.marker([latitude, longitude]).addTo(map);
    vesselMarkers.set(String(vessel.imo), vesselMarker);
  }
  vesselMarker.bindTooltip(escapeHtml(vessel.name || `IMO ${vessel.imo}`), { direction: 'top' });
  vesselMarker.bindPopup(markerPopup(vessel));
  if (open) vesselMarker.openPopup();
  return vesselMarker;
};

const refreshTrackedVessels = async () => {
  try {
    const response = await fetch('/api/vessels');
    if (!response.ok) return;
    const vessels = await response.json();
    const visibleImos = new Set();
    const bounds = [];

    vessels.forEach(vessel => {
      const vesselMarker = upsertVesselMarker(vessel);
      if (!vesselMarker) return;
      visibleImos.add(String(vessel.imo));
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
    // Keep the last markers visible if a refresh temporarily fails.
  }
};

refreshTrackedVessels();
setInterval(refreshTrackedVessels, 60_000);

form.addEventListener('submit', async event => {
  event.preventDefault();
  const imo = input.value.trim();
  message.className = 'loading';
  message.textContent = 'Searching vessel data and latest AIS position…';
  result.hidden = true;
  form.querySelector('button').disabled = true;

  try {
    const response = await fetch(`/api/lookup/${encodeURIComponent(imo)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Vessel lookup failed');

    message.textContent = data.position_available && data.historical
      ? `${data.provider}'s latest known position is historical: ${age(data.timestamp)}.`
      : data.position_available ? '' : 'Vessel found, but this provider has no stored AIS position from the last five years.';
    message.className = data.historical || !data.position_available ? 'notice' : '';
    result.innerHTML = `
      <div class="result-heading"><div><small>VESSEL FOUND</small><h2>${display(data.name)}</h2></div><span>IMO ${display(data.imo)}</span></div>
      <dl>
        <div><dt>MMSI</dt><dd>${display(data.mmsi)}</dd></div>
        <div><dt>Type</dt><dd>${display(data.vessel_type)}</dd></div>
        <div><dt>Flag</dt><dd>${display(data.flag)}</dd></div>
        <div><dt>Call sign</dt><dd>${display(data.call_sign)}</dd></div>
        <div><dt>Year built</dt><dd>${display(data.year_built)}</dd></div>
        <div><dt>Dimensions</dt><dd>${display(data.length, ' m')} × ${display(data.breadth, ' m')}</dd></div>
        <div><dt>Speed</dt><dd>${display(data.speed, ' kn')}</dd></div>
        <div><dt>Course</dt><dd>${display(data.course, '°')}</dd></div>
        <div><dt>Data source</dt><dd>${display(data.provider)}</dd></div>
        <div><dt>Position time</dt><dd>${data.timestamp ? `${new Date(data.timestamp).toLocaleString()} (${age(data.timestamp)})` : '—'}</dd></div>
      </dl>`;
    result.hidden = false;

    if (data.position_available) {
      upsertVesselMarker(data, true);
      map.setView([data.latitude, data.longitude], 9);
      setTimeout(() => map.invalidateSize(), 0);
    }
  } catch (error) {
    message.className = 'error';
    message.textContent = error.message;
  } finally {
    form.querySelector('button').disabled = false;
  }
});
