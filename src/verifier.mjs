/**
 * どこでもスクリプト＋ Stage +1
 * Windows Ver.1.0 の manifest の静的規則を扱う純粋関数。
 * Git の意味論が必要な項目は、意図的に検証しない。
 */
export const MAX_MANIFEST_BYTES = 1024 * 1024;
export const MAX_BROWSER_BUNDLE_BYTES = 64 * 1024 * 1024;

export const REQUIRED_STRINGS = Object.freeze([
  'release', 'repository', 'baseBranch', 'expectedMain', 'branch',
  'expectedHead', 'bundle', 'bundleSha256',
]);
export const REQUIRED_ARRAYS = Object.freeze(['expectedFiles', 'expectedCommits']);

const SHA40 = /^[0-9a-fA-F]{40}$/;
const SHA64 = /^[0-9a-fA-F]{64}$/;
const REPO = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\/[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98})$/;
const WINDOWS_RESERVED_NAME = /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i;

export class VerificationError extends Error {
  constructor(check, message, expected = '', actual = '') {
    super(message);
    this.name = 'VerificationError';
    this.check = check;
    this.expected = expected;
    this.actual = actual;
  }
}

function stop(check, message, expected = '', actual = '') {
  throw new VerificationError(check, message, expected, String(actual));
}

function hasControlCharacters(value) {
  return /[\x00-\x1F]/.test(value);
}

export function validateBundleFilename(filename) {
  if (typeof filename !== 'string' || !filename) return false;
  if (filename === '.' || filename === '..') return false;
  if (filename.length > 240) return false;
  if (/[\\\/:*?"<>|]/.test(filename)) return false;
  if (filename.endsWith('.') || filename.endsWith(' ')) return false;
  if (!/\.bundle$/i.test(filename)) return false;
  if (WINDOWS_RESERVED_NAME.test(filename)) return false;
  if (hasControlCharacters(filename)) return false;
  return true;
}

/** Windows側の静的manifest形式チェックに対応。Git ref形式判定は未実施。 */
export function validateManifest(manifest) {
  if (manifest === null || Array.isArray(manifest) || typeof manifest !== 'object') {
    stop('manifest.root', 'manifestのルートはJSON objectである必要があります。', 'object', typeof manifest);
  }

  const normalized = {};
  for (const name of REQUIRED_STRINGS) {
    if (!(name in manifest)) stop('manifest.' + name, '必須フィールドがありません。', name, '未指定');
    if (typeof manifest[name] !== 'string' || !manifest[name].trim()) {
      stop('manifest.' + name, '空でない文字列を指定してください。');
    }
    normalized[name] = manifest[name].trim();
  }
  for (const name of REQUIRED_ARRAYS) {
    if (!(name in manifest)) stop('manifest.' + name, '必須フィールドがありません。');
    if (!Array.isArray(manifest[name])) stop('manifest.' + name, 'JSON配列で指定してください。');
  }

  if (normalized.release.length > 100 || hasControlCharacters(normalized.release)) {
    stop('manifest.release', 'releaseは100文字以内、制御文字なしで指定してください。');
  }
  if (!REPO.test(normalized.repository) || /\.git$/i.test(normalized.repository)) {
    stop('manifest.repository', 'repositoryはowner/repository形式で指定してください。');
  }
  for (const name of ['baseBranch', 'branch']) {
    const value = normalized[name];
    if (value.length > 240 || !/^[A-Za-z0-9]/.test(value)) {
      stop('manifest.' + name, 'branch名の基本形式が不正です。');
    }
  }
  if (normalized.branch.toLowerCase() === normalized.baseBranch.toLowerCase() ||
      normalized.branch.toLowerCase() === 'main') {
    stop('manifest.branch', 'baseBranchと同名、またはmainへの直接pushとなるbranchは禁止です。');
  }
  if (!SHA40.test(normalized.expectedMain)) stop('manifest.expectedMain', '40桁のSHAを指定してください。');
  if (!SHA40.test(normalized.expectedHead)) stop('manifest.expectedHead', '40桁のSHAを指定してください。');
  if (!SHA64.test(normalized.bundleSha256)) stop('manifest.bundleSha256', '64桁のSHA256を指定してください。');
  if (!validateBundleFilename(normalized.bundle)) stop('manifest.bundle', '安全な.bundleファイル名を指定してください。');

  const filenames = [];
  for (const item of manifest.expectedFiles) {
    if (typeof item !== 'string' || !item.trim()) stop('manifest.expectedFiles', '空でないファイル名が必要です。');
    const path = item.trim();
    if (path.startsWith('/') || path.includes('\\') || /(^|\/)\.\.(\/|$)/.test(path) || hasControlCharacters(path)) {
      stop('manifest.expectedFiles', '危険な相対パスが含まれています。', '安全な相対パス', path);
    }
    if (filenames.includes(path)) stop('manifest.expectedFiles', 'ファイル名が重複しています。', '重複なし', path);
    filenames.push(path);
  }
  const commits = [];
  for (const item of manifest.expectedCommits) {
    if (typeof item !== 'string' || !SHA40.test(item)) stop('manifest.expectedCommits', 'commitは40桁のSHAが必要です。');
    const hash = item.toLowerCase();
    if (commits.includes(hash)) stop('manifest.expectedCommits', 'commit SHAが重複しています。', '重複なし', hash);
    commits.push(hash);
  }

  return {
    ...normalized,
    expectedMain: normalized.expectedMain.toLowerCase(),
    expectedHead: normalized.expectedHead.toLowerCase(),
    bundleSha256: normalized.bundleSha256.toUpperCase(),
    expectedFiles: filenames,
    expectedCommits: commits,
  };
}

export async function sha256File(file) {
  if (!globalThis.crypto?.subtle) {
    stop('browser.crypto', 'このブラウザではWeb Cryptoを利用できません。HTTPSまたはlocalhostで起動してください。');
  }
  if (file.size > MAX_BROWSER_BUNDLE_BYTES) {
    stop('bundle.size', 'Stage +1のAndroid安全上限（64 MiB）を超えています。これはbundle不正を意味しません。',
      '<= ' + MAX_BROWSER_BUNDLE_BYTES + ' bytes', file.size + ' bytes');
  }
  const contents = await file.arrayBuffer();
  const hash = await globalThis.crypto.subtle.digest('SHA-256', contents);
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('').toUpperCase();
}

/** 検証の前半のみ実施。Git履歴の検証結果を返さない。 */
export async function verifyLocalFiles(manifestFile, bundleFile) {
  if (!manifestFile) stop('manifest.exists', 'publish-manifest.jsonを選択してください。');
  if (!bundleFile) stop('bundle.exists', 'bundleを選択してください。');
  if (manifestFile.size > MAX_MANIFEST_BYTES) stop('manifest.size', 'manifestは1 MiB以下にしてください。');
  if (manifestFile.name !== 'publish-manifest.json') {
    stop('manifest.filename', 'publish-manifest.jsonを選択してください。', 'publish-manifest.json', manifestFile.name);
  }

  let manifest;
  try {
    const json = (await manifestFile.text()).replace(/^\uFEFF/, '');
    manifest = JSON.parse(json);
  } catch (error) {
    stop('manifest.json', 'JSONを解析できません。', '正常なJSON', error.message);
  }
  const normalized = validateManifest(manifest);
  if (bundleFile.name !== normalized.bundle) {
    stop('bundle.filename', 'bundle名がmanifestと一致しません。', normalized.bundle, bundleFile.name);
  }
  const actualHash = await sha256File(bundleFile);
  if (actualHash !== normalized.bundleSha256) {
    stop('bundle.sha256', 'bundleのSHA256が一致しません。', normalized.bundleSha256, actualHash);
  }
  return {
    manifest: normalized,
    bundleSize: bundleFile.size,
    actualHash,
    verifiedChecks: ['manifest形式', 'bundleファイル名', 'bundle SHA256'],
    unverifiedChecks: ['git check-ref-format', 'git bundle verify', 'bundle HEAD', 'base HEAD',
      'ancestor', 'diff files', 'diff --check', 'commit順序', 'remote同名branch', 'GitHub push'],
  };
}
