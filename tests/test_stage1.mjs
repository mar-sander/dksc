/** Stage +1で確認済みの3経路を、同じ公開用moduleで回帰確認します。 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { verifyLocalFiles } from '../src/verifier.mjs';

const fixture = new URL('./fixtures/', import.meta.url);
const manifestBytes = await readFile(new URL('publish-manifest.json', fixture));
const manifest = JSON.parse(manifestBytes);
const bundleBytes = await readFile(new URL(manifest.bundle, fixture));

function manifestFile(value = manifest) {
  return new File([JSON.stringify(value)], 'publish-manifest.json');
}

test('Stage +1正常：静的検証PASS・Git履歴は未検証と表示', async () => {
  const result = await verifyLocalFiles(manifestFile(), new File([bundleBytes], manifest.bundle));
  assert.equal(result.actualHash, manifest.bundleSha256.toUpperCase());
  assert.deepEqual(result.verifiedChecks, ['manifest形式', 'bundleファイル名', 'bundle SHA256']);
  assert.ok(result.unverifiedChecks.includes('git bundle verify'));
  assert.ok(result.unverifiedChecks.includes('commit順序'));
});

test('Stage +1：filename不一致はbundle.filename STOP', async () => {
  await assert.rejects(verifyLocalFiles(manifestFile(), new File([bundleBytes], 'wrong.bundle')),
    error => error.check === 'bundle.filename');
});

test('Stage +1：SHA256不一致はbundle.sha256 STOP', async () => {
  await assert.rejects(verifyLocalFiles(manifestFile({ ...manifest, bundleSha256: '0'.repeat(64) }),
    new File([bundleBytes], manifest.bundle)), error => error.check === 'bundle.sha256');
});
