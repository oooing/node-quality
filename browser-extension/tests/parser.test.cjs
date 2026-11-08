'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {isIPv4, readTask, parseRisk} = require('../parser.js');

const IP = '203.0.113.7';
const TOKEN = 'aB09_-'.repeat(5) + '12';

function element(text = '', style = {}, visible = true, parent = null) {
  return {
    textContent: text, hidden: false, parentElement: parent,
    style: {display: 'block', visibility: 'visible', opacity: '1', ...style},
    getClientRects: () => visible ? [{}] : []
  };
}

function page(options = {}) {
  const risk = element('', options.riskStyle, options.riskVisible !== false);
  const value = element(options.score ?? '7%', options.valueStyle, options.valueVisible !== false, risk);
  const label = element(options.label ?? '极度纯净', options.labelStyle, options.labelVisible !== false, risk);
  risk.querySelectorAll = selector => selector === '.value'
    ? Array.from({length: options.valueCount ?? 1}, () => value)
    : Array.from({length: options.labelCount ?? 1}, () => label);
  return {
    defaultView: {getComputedStyle: item => item.style},
    querySelectorAll: selector => selector === 'script'
      ? [{textContent: options.script ?? `window.ip = '${IP}';`}]
      : Array.from({length: options.riskCount ?? 1}, () => risk)
  };
}

test('IPv4 validation accepts canonical addresses only', () => {
  for (const ip of [IP, '0.0.0.0', '255.255.255.255']) assert.equal(isIPv4(ip), true);
  for (const ip of ['01.2.3.4', '256.1.2.3', '1.2.3', '1.2.3.4.5', '::1', '', null]) assert.equal(isIPv4(ip), false);
});

test('only the exact 32-character panel task fragment activates a page', () => {
  const base = `https://ping0.cc/ip/${IP}`;
  assert.deepEqual(readTask(`${base}#clash-panel=${TOKEN}`), {job_id: TOKEN, ip: IP, page_url: base});
  for (const url of [base, `${base}#other=${TOKEN}`, `${base}#clash-panel=${TOKEN}&other=1`, `${base}#clash-panel=${TOKEN.slice(1)}`, `${base}#clash-panel=${TOKEN}!`, `http://ping0.cc/ip/${IP}#clash-panel=${TOKEN}`, `https://ping0.cc.evil.test/ip/${IP}#clash-panel=${TOKEN}`, `https://ping0.cc:444/ip/${IP}#clash-panel=${TOKEN}`, `https://ping0.cc/ip/01.2.3.4#clash-panel=${TOKEN}`]) assert.equal(readTask(url), null, url);
});

test('reads the unique current risk and script-assigned matching IPv4', () => {
  assert.deepEqual(parseRisk(page(), IP), {ip: IP, score: 7, label: '极度纯净'});
  assert.deepEqual(parseRisk(page({score: ' 12.5 % ', label: '  中等\n 风险  '}), IP), {ip: IP, score: 12.5, label: '中等 风险'});
  assert.equal(parseRisk(page({score: '100%'}), IP).score, 100);
  assert.equal(parseRisk(page({score: '0%'}), IP).score, 0);
});

test('desktop task carries only a valid loopback callback port', () => {
  const {callbackUrl} = require('../parser.js');
  const url=`https://ping0.cc/ip/${IP}#node-quality=${TOKEN}&port=18765`;
  assert.deepEqual(readTask(url), {job_id:TOKEN, ip:IP, page_url:`https://ping0.cc/ip/${IP}`, port:18765});
  assert.equal(callbackUrl(url),'http://127.0.0.1:18765/api/ping0/result');
  for(const port of ['80','1023','65536','017786','17786&url=https://example.invalid']) {
    assert.equal(readTask(`https://ping0.cc/ip/${IP}#node-quality=${TOKEN}&port=${port}`),null);
  }
});

test('a challenge or incomplete page is not a result', () => {
  for (const options of [{script: ''}, {riskCount: 0}, {valueCount: 0}, {labelCount: 0}, {label: ''}, {label: 'x'.repeat(121)}]) assert.equal(parseRisk(page(options), IP), null);
});

test('rejects wrong and ambiguous query IP assignments', () => {
  assert.equal(parseRisk(page({script: "window.ip='1.2.3.4';"}), IP), null);
  assert.equal(parseRisk(page({script: `window.ip='${IP}'; window.ip='${IP}';`}), IP), null);
});

test('rejects ambiguous risk containers, value nodes and labels', () => {
  for (const options of [{riskCount: 2}, {valueCount: 2}, {labelCount: 2}]) assert.equal(parseRisk(page(options), IP), null);
});

test('rejects hidden risk text and hidden ancestors', () => {
  for (const options of [{riskVisible: false}, {valueVisible: false}, {labelVisible: false}, {valueStyle: {visibility: 'hidden'}}, {labelStyle: {opacity: '0'}}, {riskStyle: {display: 'none'}}, {riskStyle: {contentVisibility: 'hidden'}}]) assert.equal(parseRisk(page(options), IP), null);
});

test('rejects numbers outside the percentage format and range', () => {
  for (const score of ['-1%', '101%', 'NaN%', '7', 'risk 7%', '7% other', '1e1%', 'Infinity%']) assert.equal(parseRisk(page({score}), IP), null, score);
});
