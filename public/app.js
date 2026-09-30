const loginPanel = document.querySelector('#login-panel');
const transferPanel = document.querySelector('#transfer-panel');
const loginForm = document.querySelector('#login-form');
const pinInput = document.querySelector('#pin-input');
const loginError = document.querySelector('#login-error');
const uploadError = document.querySelector('#upload-error');
const fileInput = document.querySelector('#file-input');
const dropZone = document.querySelector('#drop-zone');
const uploadQueue = document.querySelector('#upload-queue');
const fileList = document.querySelector('#file-list');
const filesSummary = document.querySelector('#files-summary');
const maxSizeLabel = document.querySelector('#max-size');

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = -1;
  do { value /= 1024; unit += 1; } while (value >= 1024 && unit < units.length - 1);
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function setConnected(connected) {
  loginPanel.hidden = connected;
  transferPanel.hidden = !connected;
  if (!connected) {
    pinInput.value = '';
    pinInput.focus();
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, { credentials: 'same-origin', ...options });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) setConnected(false);
    throw new Error(result.error || '请求失败，请重试。');
  }
  return result;
}

async function checkSession() {
  try {
    const status = await api('/api/status');
    setConnected(status.authenticated);
    if (status.authenticated) await refreshFiles();
  } catch (error) {
    loginError.textContent = error.message;
  }
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginError.textContent = '';
  const button = loginForm.querySelector('button');
  button.disabled = true;
  try {
    await api('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: pinInput.value.trim() }),
    });
    setConnected(true);
    await refreshFiles();
  } catch (error) {
    loginError.textContent = error.message;
    pinInput.select();
  } finally {
    button.disabled = false;
  }
});

document.querySelector('#logout-button').addEventListener('click', async () => {
  await api('/api/logout', { method: 'POST' }).catch(() => {});
  setConnected(false);
});

document.querySelector('#browse-button').addEventListener('click', () => fileInput.click());
dropZone.addEventListener('click', (event) => {
  if (event.target.closest('button')) return;
  fileInput.click();
});
dropZone.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    fileInput.click();
  }
});
fileInput.addEventListener('change', () => {
  queueFiles([...fileInput.files]);
  fileInput.value = '';
});

for (const eventName of ['dragenter', 'dragover']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add('is-dragging');
  });
}
for (const eventName of ['dragleave', 'drop']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove('is-dragging');
  });
}
dropZone.addEventListener('drop', (event) => queueFiles([...event.dataTransfer.files]));

function queueFiles(files) {
  if (!files.length) return;
  uploadError.textContent = '';
  for (const file of files) uploadFile(file);
}

function uploadFile(file) {
  const row = document.createElement('div');
  row.className = 'queue-item';
  const details = document.createElement('div');
  details.className = 'queue-details';
  const name = document.createElement('span');
  name.className = 'queue-name';
  name.textContent = file.name;
  const state = document.createElement('span');
  state.className = 'queue-state';
  state.textContent = `等待发送 · ${formatBytes(file.size)}`;
  const progress = document.createElement('progress');
  progress.max = 100;
  progress.value = 0;
  details.append(name, state, progress);
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'icon-button queue-cancel';
  cancel.setAttribute('aria-label', `移除 ${file.name}`);
  cancel.textContent = '×';
  cancel.addEventListener('click', () => {
    if (row.dataset.done !== 'true') return;
    row.remove();
  });
  row.append(details, cancel);
  uploadQueue.prepend(row);

  const request = new XMLHttpRequest();
  const cancelRequest = () => request.abort();
  cancel.addEventListener('click', () => {
    if (row.dataset.done !== 'true') cancelRequest();
  }, { once: true });
  request.open('POST', `/api/upload?name=${encodeURIComponent(file.name)}`);
  request.withCredentials = true;
  request.upload.addEventListener('progress', (event) => {
    if (!event.lengthComputable) return;
    progress.value = Math.round((event.loaded / event.total) * 100);
    state.textContent = `正在发送 ${progress.value}% · ${formatBytes(event.loaded)} / ${formatBytes(file.size)}`;
  });
  request.addEventListener('load', async () => {
    let result = {};
    try { result = JSON.parse(request.responseText); } catch {}
    if (request.status >= 200 && request.status < 300) {
      progress.value = 100;
      state.textContent = `已发送 · ${formatBytes(file.size)}`;
      row.dataset.done = 'true';
      await refreshFiles();
    } else {
      row.dataset.done = 'true';
      state.textContent = result.error || '发送失败';
      state.classList.add('error-text');
      uploadError.textContent = result.error || '发送失败，请重试。';
      if (request.status === 401) setConnected(false);
    }
  });
  request.addEventListener('error', () => {
    row.dataset.done = 'true';
    state.textContent = '连接中断，请检查网络后重试';
    state.classList.add('error-text');
  });
  request.addEventListener('abort', () => {
    row.dataset.done = 'true';
    state.textContent = '已取消';
  });
  request.send(file);
}

async function refreshFiles() {
  try {
    const result = await api('/api/files');
    maxSizeLabel.textContent = formatBytes(result.maxBytes);
    const totalSize = result.files.reduce((sum, file) => sum + file.size, 0);
    filesSummary.textContent = `${result.files.length} 个文件 · 共 ${formatBytes(totalSize)}`;
    fileList.replaceChildren();
    if (!result.files.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.innerHTML = '<span class="empty-icon" aria-hidden="true">↘</span><strong>还没有收到文件</strong><span>发送的文件会显示在这里</span>';
      fileList.append(empty);
      return;
    }
    for (const file of result.files) fileList.append(makeFileRow(file));
  } catch (error) {
    if (!error.message.includes('PIN')) filesSummary.textContent = '文件列表暂时无法加载';
  }
}

function makeFileRow(file) {
  const row = document.createElement('article');
  row.className = 'file-row';
  const icon = document.createElement('div');
  icon.className = 'file-icon';
  icon.textContent = file.name.includes('.') ? file.name.split('.').pop().slice(0, 4).toUpperCase() : 'FILE';
  const info = document.createElement('div');
  info.className = 'file-info';
  const name = document.createElement('strong');
  name.className = 'file-name';
  name.textContent = file.name;
  name.title = file.name;
  const meta = document.createElement('span');
  meta.textContent = `${formatBytes(file.size)} · ${new Date(file.modified).toLocaleString()}`;
  info.append(name, meta);
  const actions = document.createElement('div');
  actions.className = 'file-actions';
  const download = document.createElement('a');
  download.className = 'button button-download';
  download.href = `/api/files/${encodeURIComponent(file.id)}`;
  download.textContent = '下载';
  download.setAttribute('aria-label', `下载 ${file.name}`);
  const remove = document.createElement('button');
  remove.className = 'icon-button remove-button';
  remove.type = 'button';
  remove.textContent = '×';
  remove.setAttribute('aria-label', `删除 ${file.name}`);
  remove.addEventListener('click', async () => {
    if (!window.confirm(`删除“${file.name}”？`)) return;
    try {
      await api(`/api/files/${encodeURIComponent(file.id)}`, { method: 'DELETE' });
      await refreshFiles();
    } catch (error) {
      uploadError.textContent = error.message;
    }
  });
  actions.append(download, remove);
  row.append(icon, info, actions);
  return row;
}

document.querySelector('#refresh-button').addEventListener('click', refreshFiles);
checkSession();
setInterval(() => {
  if (!transferPanel.hidden) refreshFiles();
}, 8000);
