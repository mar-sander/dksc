import { verifyLocalFiles, VerificationError } from './verifier.mjs';

const manifestField = document.querySelector('#manifest');
const bundleField = document.querySelector('#bundle');
const verifyButton = document.querySelector('#verify');
const resultPanel = document.querySelector('#result');
const statusTitle = document.querySelector('#status-title');
const statusSummary = document.querySelector('#status-summary');
const details = document.querySelector('#details');

function line(label, value, style = '') {
  const item = document.createElement('div');
  item.className = 'result-line ' + style;
  const key = document.createElement('span');
  key.textContent = label;
  const val = document.createElement('strong');
  val.textContent = value;
  item.append(key, val);
  return item;
}

function setStatus(kind, title, summary) {
  resultPanel.dataset.status = kind;
  statusTitle.textContent = title;
  statusSummary.textContent = summary;
}

function showFailure(error) {
  setStatus('error', 'STOP — 検証を中断', '公開処理は行っていません。選択したファイルを確認してください。');
  details.replaceChildren();
  details.append(line('停止check', error.check || 'unexpected', 'error-line'));
  details.append(line('理由', error.message));
  if (error.expected) details.append(line('Expected', error.expected));
  if (error.actual) details.append(line('Actual', error.actual));
}

verifyButton.addEventListener('click', async () => {
  verifyButton.disabled = true;
  const previousLabel = verifyButton.textContent;
  verifyButton.textContent = '検証中…';
  setStatus('running', '検証中', 'ローカルファイルだけを読み取っています。');
  details.replaceChildren();
  try {
    const outcome = await verifyLocalFiles(manifestField.files[0], bundleField.files[0]);
    setStatus('success', 'ブラウザ検証 PASS', 'SHA256まで一致しました。ただし、Git履歴・公開可能性は未判定です。');
    details.append(line('Release', outcome.manifest.release));
    details.append(line('Repository', outcome.manifest.repository));
    details.append(line('Target branch', outcome.manifest.branch));
    details.append(line('expectedMain', outcome.manifest.expectedMain));
    details.append(line('expectedHead', outcome.manifest.expectedHead));
    details.append(line('File size', (outcome.bundleSize / 1024 / 1024).toFixed(2) + ' MiB'));
    details.append(line('SHA256', outcome.actualHash, 'hash-line'));
    details.append(line('ブラウザ確認', outcome.verifiedChecks.join(' / ')));
    details.append(line('未確認', outcome.unverifiedChecks.join(' / ')));
  } catch (error) {
    showFailure(error instanceof VerificationError ? error : {
      check: 'unexpected', message: error && error.message || '不明なエラーです.',
    });
  } finally {
    verifyButton.disabled = false;
    verifyButton.textContent = previousLabel;
  }
});
