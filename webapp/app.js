const tg = window.Telegram.WebApp;
tg.expand();

const map = L.map('map').setView([55.75, 37.61], 10);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, attribution: '&copy; OpenStreetMap'
}).addTo(map);

const drawnItems = new L.FeatureGroup().addTo(map);
const drawControl = new L.Control.Draw({
  draw: {
    polygon: true, marker: false, circle: false, circlemarker: false, polyline: false, rectangle: true
  },
  edit: { featureGroup: drawnItems }
});
map.addControl(drawControl);

let feature = null;

map.on(L.Draw.Event.CREATED, function (e) {
  drawnItems.clearLayers();
  const layer = e.layer;
  drawnItems.addLayer(layer);
  feature = layer.toGeoJSON();
  document.getElementById('send').disabled = false;
});

document.getElementById('clear').onclick = () => {
  drawnItems.clearLayers(); feature = null; document.getElementById('send').disabled = true;
};

document.getElementById('send').onclick = () => {
  if (!feature) return;
  // Отправляем как GeoJSON Feature
  tg.sendData(JSON.stringify(feature));
  tg.close();
};