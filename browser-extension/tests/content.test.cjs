'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const parser = require('../parser.js');

const IP = '203.0.113.7';
const TOKEN = 'aB09_-'.repeat(5) + '12';
const PAGE = `https://ping0.cc/ip/${IP}`;
const flush = () => new Promise(resolve => setImmediate(resolve));

function harness({url = `${PAGE}#clash-panel=${TOKEN}`, ready = false, reply = async () => ({ok: true, applied_to_current: true})} = {}) {
  const elements = [];
  const frames = [];
  const messages = [];
  const observers = [];
  let available = ready;
  let parseCount = 0;
  function element(tag) {
    const node = {tag, children: [], attributes: {}, events: {}, hidden: false, textContent: '',
      append(...children) { this.children.push(...children); },
      setAttribute(key, value) { this.attributes[key] = value; },
      addEventListener(name, callback) { this.events[name] = callback; },
      remove() { this.removed = true; },
      classList: {add() {}, remove() {}}
    };
    elements.push(node);
    return node;
  }
  const document = {createElement: element, body: element('body'), documentElement: {}};
  Object.defineProperty(document, 'cookie', {get() { assert.fail('Cookies must not be read'); }});
  const window = {}; window.top = window;
  const context = {
    window, document, location: {href: url},
    ClashPanelPing0: {...parser, parseRisk() { parseCount++; return available ? {ip: IP, score: 7, label: '极度纯净'} : null; }},
    MutationObserver: class {
      constructor(callback) { this.callback = callback; this.disconnected = false; observers.push(this); }
      observe() { this.observing = true; }
      disconnect() { this.disconnected = true; }
    },
    requestAnimationFrame: callback => frames.push(callback),
    chrome: {runtime: {sendMessage: async message => { messages.push(message); return await reply(); }}}
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../content.js'), 'utf8'), context);
  return {
    elements, messages, observers,
    ready() { available = true; },
    mutate() { for (const observer of observers) if (!observer.disconnected) observer.callback(); },
    paint() { for (const callback of frames.splice(0)) callback(); },
    get parseCount() { return parseCount; }
  };
}

test('ordinary Ping0 visits without a task do nothing', () => {
  const page = harness({url: PAGE, ready: true});
  assert.equal(page.observers.length, 0);
  assert.equal(page.messages.length, 0);
  assert.equal(page.elements.length, 1);
});

test('waits for the result after page changes and sends once', async () => {
  const page = harness();
  assert.equal(page.messages.length, 0);
  page.ready();
  page.mutate(); page.mutate(); page.paint();
  await flush();
  assert.equal(page.messages.length, 1);
  assert.equal(page.messages[0].type, 'PING0_RESULT');
  assert.equal(page.messages[0].job_id, TOKEN);
  assert.equal(page.messages[0].page_url, PAGE);
  assert.equal(page.observers[0].disconnected, true);
  assert.equal(page.elements.find(node => node.tag === 'span').textContent, '检测结果已保存。');
  page.mutate(); page.paint(); await flush();
  assert.equal(page.messages.length, 1);
});

test('retry only re-sends the captured result without re-reading or querying the page', async () => {
  let attempts = 0;
  const page = harness({ready: true, reply: async () => ++attempts === 1 ? {ok: false, error: '请启动本地面板'} : {ok: true, applied_to_current: false}});
  await flush();
  const retry = page.elements.find(node => node.tag === 'button');
  assert.equal(retry.hidden, false);
  assert.equal(page.parseCount, 1);
  retry.events.click();
  await flush();
  assert.equal(page.messages.length, 2);
  assert.deepEqual(page.messages[0], page.messages[1]);
  assert.equal(page.parseCount, 1);
  assert.equal(retry.hidden, true);
  assert.equal(page.elements.find(node => node.tag === 'span').textContent, '已保存到之前地址的记录。');
  retry.events.click(); await flush();
  assert.equal(page.messages.length, 2);
});
