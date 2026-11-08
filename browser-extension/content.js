'use strict';

(() => {
  if (window.top !== window) return;
  const task = ClashPanelPing0.readTask(location.href);
  if (!task) return;

  const bar = document.createElement('div');
  bar.id = 'clash-ip-panel-ping0-result';
  bar.setAttribute('role', 'status');
  bar.setAttribute('aria-live', 'polite');
  const text = document.createElement('span');
  text.textContent = '等待网页显示检测结果。';
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.textContent = '重新保存';
  retry.hidden = true;
  bar.append(text, retry);
  document.body.append(bar);

  let captured = null;
  let sending = false;
  let finished = false;
  let scheduled = false;

  async function saveResult() {
    if (!captured || sending || finished) return;
    sending = true;
    retry.hidden = true;
    text.textContent = '正在保存检测结果。';
    bar.classList.remove('save-error');
    try {
      const response = await chrome.runtime.sendMessage({type: 'PING0_RESULT', ...task, ...captured});
      if (!response?.ok) throw new Error(response?.error || '保存失败，请确认云鉴已打开。');
      finished = true;
      text.textContent = response.applied_to_current ? '检测结果已保存。' : '已保存到之前地址的记录。';
    } catch (error) {
      text.textContent = error.message || '保存失败，请确认云鉴已打开。';
      bar.classList.add('save-error');
      retry.hidden = false;
    } finally {
      sending = false;
    }
  }

  function inspect() {
    scheduled = false;
    if (captured) return;
    const currentTask = ClashPanelPing0.readTask(location.href);
    if (!currentTask || currentTask.job_id !== task.job_id || currentTask.ip !== task.ip || currentTask.port !== task.port) {
      observer.disconnect();
      bar.remove();
      return;
    }
    const result = ClashPanelPing0.parseRisk(document, task.ip);
    if (!result) return;
    captured = Object.freeze(result);
    observer.disconnect();
    void saveResult();
  }

  const observer = new MutationObserver(() => {
    if (scheduled || captured) return;
    scheduled = true;
    requestAnimationFrame(inspect);
  });
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['class', 'style', 'hidden']
  });
  retry.addEventListener('click', () => { void saveResult(); });
  inspect();
})();
