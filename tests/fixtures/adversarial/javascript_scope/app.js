function helper() { return 'global'; }
function actual() { return helper(); }
function member(obj) { return obj.helper(); }
function commentOnly() {
  // helper();
  return 0;
}
function stringOnly() { return "helper()"; }
function outer() {
  function inner() { return helper(); }
  return 0;
}
