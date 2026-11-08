'use strict';

(() => {
  const TOKEN_PATTERN = /^[A-Za-z0-9_-]{32}$/;

  function isIPv4(value) {
    if (typeof value !== 'string') return false;
    const parts = value.split('.');
    return parts.length === 4 && parts.every(part => /^(0|[1-9][0-9]{0,2})$/.test(part) && Number(part) <= 255);
  }

  function readPageUrl(value) {
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.hostname !== 'ping0.cc' || url.port || url.username || url.password) return null;
      const match = /^\/ip\/([^/]+)\/?$/.exec(url.pathname);
      if (!match || !isIPv4(match[1])) return null;
      const ip = match[1];
      const hash = url.hash;
      url.hash = '';
      return {ip, hash, page_url: url.href};
    } catch {
      return null;
    }
  }

  function readTask(value) {
    const page = readPageUrl(value);
    const match = page && /^#clash-panel=([A-Za-z0-9_-]{32})$/.exec(page.hash);
    if (match) return {job_id: match[1], ip: page.ip, page_url: page.page_url};
    const desktop = page && /^#node-quality=([A-Za-z0-9_-]{32})&port=([1-9][0-9]{3,4})$/.exec(page.hash);
    if (!desktop || Number(desktop[2]) < 1024 || Number(desktop[2]) > 65535) return null;
    return {job_id: desktop[1], ip: page.ip, page_url: page.page_url, port: Number(desktop[2])};
  }

  function callbackUrl(value) {
    const task = readTask(value);
    if (!task) throw new Error('回填任务标记无效。');
    return `http://127.0.0.1:${task.port || 17786}/api/ping0/result`;
  }

  function isVisible(element, view) {
    if (!element || !element.getClientRects().length) return false;
    for (let current = element; current; current = current.parentElement) {
      const style = view.getComputedStyle(current);
      if (current.hidden || style.display === 'none' || ['hidden', 'collapse'].includes(style.visibility) || style.opacity === '0' || style.contentVisibility === 'hidden') return false;
    }
    return true;
  }

  function parseRisk(document, expectedIp) {
    if (!isIPv4(expectedIp)) return null;
    const scripts = Array.from(document.querySelectorAll('script'), element => element.textContent || '').join('\n');
    const assigned = Array.from(scripts.matchAll(/\bwindow\s*\.\s*ip\s*=\s*(["'])([^"']+)\1/g));
    if (assigned.length !== 1 || assigned[0][2] !== expectedIp) return null;
    const current = document.querySelectorAll('.riskitem.riskcurrent');
    if (current.length !== 1 || !isVisible(current[0], document.defaultView)) return null;
    const values = current[0].querySelectorAll('.value');
    const labels = current[0].querySelectorAll('.lab');
    if (values.length !== 1 || labels.length !== 1 || !isVisible(values[0], document.defaultView) || !isVisible(labels[0], document.defaultView)) return null;
    const number = /^([0-9]+(?:\.[0-9]+)?)\s*%$/.exec(values[0].textContent.trim());
    const label = labels[0].textContent.replace(/\s+/g, ' ').trim();
    if (!number || !label || label.length > 120) return null;
    const score = Number(number[1]);
    if (!Number.isFinite(score) || score < 0 || score > 100) return null;
    return {ip: expectedIp, score, label};
  }

  function resultPayload(message, sender, extensionId) {
    if (message?.type !== 'PING0_RESULT' || sender?.id !== extensionId || sender.frameId !== 0) throw new Error('结果来源无效。');
    const page = readPageUrl(sender.url);
    const task = readTask(sender.url);
    const submittedPage = readPageUrl(message.page_url);
    if (!page || !submittedPage || submittedPage.hash || page.page_url !== submittedPage.page_url || page.ip !== message.ip) throw new Error('网页与查询 IP 不一致。');
    if (!TOKEN_PATTERN.test(message.job_id || '') || !task || task.job_id !== message.job_id) throw new Error('面板任务标记无效，请从节点面板重新打开补查。');
    if (typeof message.score !== 'number' || !Number.isFinite(message.score) || message.score < 0 || message.score > 100) throw new Error('风险值无效。');
    if (typeof message.label !== 'string' || !message.label.trim() || message.label.length > 120) throw new Error('风险说明无效。');
    return {
      job_id: message.job_id,
      ip: page.ip,
      score: message.score,
      label: message.label.replace(/\s+/g, ' ').trim(),
      page_url: page.page_url
    };
  }

  const api = Object.freeze({isIPv4, readPageUrl, readTask, callbackUrl, parseRisk, resultPayload});
  globalThis.ClashPanelPing0 = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
