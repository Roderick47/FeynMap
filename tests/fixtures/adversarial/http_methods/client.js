function readItems() { return fetch('/items'); }
function writeItems() { return fetch('/items', {method: 'POST'}); }
