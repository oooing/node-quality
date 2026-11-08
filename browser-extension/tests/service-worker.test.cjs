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
const ID = 'local-extension-id';
const validMessage = () => ({type: 'PING0_RESULT', job_id: TOKEN, ip: IP, score: 7, label: '极度纯净', page_url: PAGE});
const validSender = () => ({id: ID, frameId: 0, url: `${PAGE}#clash-panel=${TOKEN}`});

function worker(fetchHandler = async () => ({ok: true, json: async () => ({record: {id: 1}, applied_to_current: true})})) {
  let listener;
  const calls = [];
  const context = {
    importScripts: filename => assert.equal(filename, 'parser.js'),
    ClashPanelPing0: parser,
    AbortSignal,
    chrome: {runtime: {id: ID, onMessage: {addListener: callback => { listener = callback; }}}},
    fetch: async (url, options) => { calls.push({url, options}); return await fetchHandler(url, options); }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../service-worker.js'), 'utf8'), context);
  return {
    calls, listener,
    send: (message = validMessage(), sender = validSender()) => new Promise(resolve => {
      const keepOpen = listener(message, sender, resolve);
      assert.equal(keepOpen, true);
    })
  };
}

test('manifest uses MV3, narrow content matches and only localhost host permission', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '../manifest.json'), 'utf8'));
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.permissions, undefined);
  assert.equal(manifest.icons, undefined);
  assert.deepEqual(manifest.host_permissions, ['http://127.0.0.1/*']);
  assert.deepEqual(manifest.content_scripts[0].matches, ['https://ping0.cc/ip/*']);
  assert.equal(manifest.content_scripts[0].all_frames, false);
  for (const filename of [manifest.background.service_worker, ...manifest.content_scripts[0].js, ...manifest.content_scripts[0].css]) assert.ok(fs.existsSync(path.join(__dirname, '..', filename)), filename);
});

test('valid result only posts normalized fields to the fixed local callback', async () => {
  const sw = worker();
  const message = {...validMessage(), url: 'https://example.invalid/ignored', checked_at: 'client supplied time'};
  const response = await sw.send(message);
  assert.equal(response.ok, true);
  assert.equal(response.applied_to_current, true);
  assert.equal(sw.calls.length, 1);
  const {url, options} = sw.calls[0];
  assert.equal(url, 'http://127.0.0.1:17786/api/ping0/result');
  assert.equal(options.method, 'POST');
  assert.equal(options.credentials, 'omit');
  assert.equal(options.redirect, 'error');
  assert.deepEqual(JSON.parse(options.body), {job_id: TOKEN, ip: IP, score: 7, label: '极度纯净', page_url: PAGE});
});

test('keeps the old-IP save response distinct', async () => {
  const sw = worker(async () => ({ok: true, json: async () => ({record: {id: 1}, applied_to_current: false})}));
  assert.equal((await sw.send()).applied_to_current, false);
});

test('desktop results go to the task port, never to the legacy panel or a payload URL', async () => {
  const sw=worker();
  const response=await sw.send({...validMessage(),port:9999,url:'https://unrelated.invalid'},
    {...validSender(),url:`${PAGE}#node-quality=${TOKEN}&port=18765`});
  assert.equal(response.ok,true);
  assert.equal(sw.calls[0].url,'http://127.0.0.1:18765/api/ping0/result');
});

test('unknown message types are ignored with no request', () => {
  const sw = worker();
  const result = sw.listener({type: 'FETCH', url: 'https://example.invalid'}, validSender(), () => assert.fail('Unexpected reply'));
  assert.equal(result, false);
  assert.equal(sw.calls.length, 0);
});

test('rejects other origins, frames, extensions and mismatched IPs before fetch', async () => {
  for (const overrides of [{id: 'other-extension'}, {frameId: 1}, {url: `https://ping0.cc.evil.test/ip/${IP}#clash-panel=${TOKEN}`}, {url: `https://ping0.cc/ip/1.2.3.4#clash-panel=${TOKEN}`}, {url: PAGE}]) {
    const sw = worker();
    assert.equal((await sw.send(validMessage(), {...validSender(), ...overrides})).ok, false);
    assert.equal(sw.calls.length, 0);
  }
});

test('rejects invalid fields and task mismatches before fetch', async () => {
  for (const overrides of [{job_id: 'short'}, {job_id: 'z'.repeat(32)}, {score: '7'}, {score: -1}, {score: 101}, {score: NaN}, {label: ''}, {label: 'x'.repeat(121)}, {ip: '1.2.3.4'}, {page_url: `${PAGE}#clash-panel=${TOKEN}`}]) {
    const sw = worker();
    assert.equal((await sw.send({...validMessage(), ...overrides})).ok, false);
    assert.equal(sw.calls.length, 0);
  }
});

test('local API errors are returned for a user-triggered retry', async () => {
  const sw = worker(async () => ({ok: false, status: 410, json: async () => ({error: '补查任务已过期'})}));
  const response = await sw.send();
  assert.equal(response.ok, false);
  assert.equal(response.error, '补查任务已过期');
  assert.equal(sw.calls.length, 1);
});

test('network, invalid JSON and missing save confirmation fail without automatic retry', async () => {
  for (const fetchHandler of [async () => { throw new Error('network unavailable'); }, async () => ({ok: true, json: async () => { throw new Error('invalid JSON'); }}), async () => ({ok: true, json: async () => ({applied_to_current: true})})]) {
    const sw = worker(fetchHandler);
    assert.equal((await sw.send()).ok, false);
    assert.equal(sw.calls.length, 1);
  }
});
