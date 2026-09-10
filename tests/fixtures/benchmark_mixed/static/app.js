function helper() { return 1; }
function loadItems() {
  helper();
  return fetch('/api/items');
}
function idle() { return 0; }
