'use strict';

importScripts('parser.js');

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'PING0_RESULT') return false;
  (async () => {
    try {
      const payload = ClashPanelPing0.resultPayload(message, sender, chrome.runtime.id);
      const response = await fetch(ClashPanelPing0.callbackUrl(sender.url), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
        credentials: 'omit',
        redirect: 'error',
        signal: AbortSignal.timeout(10000)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `面板保存失败（${response.status}）。`);
      if (!data.record || typeof data.applied_to_current !== 'boolean') throw new Error('面板未确认保存结果，请重试。');
      sendResponse({ok: true, applied_to_current: data.applied_to_current});
    } catch (error) {
      sendResponse({ok: false, error: error.message || '暂时连不上云鉴，请确认应用已打开。'});
    }
  })();
  return true;
});
