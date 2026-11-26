// Regression: every toast in #toasts must disappear even if new ones arrive.
import test from 'node:test';
import assert from 'node:assert/strict';

class FakeNode {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.style = {};
    this.parentNode = null;
    this.className = '';
    this.textContent = '';
  }

  append(...nodes) {
    for (const node of nodes) {
      if (!node) continue;
      node.parentNode = this;
      this.children.push(node);
    }
  }

  remove() {
    if (!this.parentNode) return;
    const index = this.parentNode.children.indexOf(this);
    if (index >= 0) this.parentNode.children.splice(index, 1);
    this.parentNode = null;
  }

  get firstElementChild() {
    return this.children[0] || null;
  }
}

let host = null;
let timers = new Map();
let nextTimer = 1;
let now = 0;

function reset() {
  host = new FakeNode('div');
  host.id = 'toasts';
  timers = new Map();
  nextTimer = 1;
  now = 0;
  globalThis.document = {
    createElement: (tag) => new FakeNode(tag),
    createTextNode: (text) => {
      const node = new FakeNode('#text');
      node.textContent = text;
      return node;
    },
    getElementById: (id) => (id === 'toasts' ? host : null),
  };
  globalThis.window = {
    setTimeout(fn, ms) {
      const id = nextTimer++;
      timers.set(id, { fn, at: now + ms });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
  };
}

function advance(ms) {
  const until = now + ms;
  for (;;) {
    let next = null;
    for (const [id, timer] of timers) {
      if (timer.at <= until && (!next || timer.at < next.timer.at)) {
        next = { id, timer };
      }
    }
    if (!next) break;
    timers.delete(next.id);
    now = next.timer.at;
    next.timer.fn();
  }
  now = until;
}

reset();
const { toast } = await import('../yumi/webui/static/js/ui.js');

test('all toasts disappear on their own timers', () => {
  reset();
  toast('one');
  toast('two');
  assert.equal(host.children.length, 2);
  advance(4200);
  assert.ok(host.children.every((node) => node.style.opacity === '0'));
  advance(220);
  assert.equal(host.children.length, 0);
});

test('a new toast does not cancel an older toast timer', () => {
  reset();
  toast('first');
  advance(2000);
  toast('second');
  advance(2200); // t=4200: only the first toast fades
  assert.equal(host.children[0].style.opacity, '0');
  assert.equal(host.children[1].style.opacity, undefined);
  advance(2220); // t=6420: both are removed
  assert.equal(host.children.length, 0);
});
