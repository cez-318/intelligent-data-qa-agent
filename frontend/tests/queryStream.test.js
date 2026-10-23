import test from 'node:test';
import assert from 'node:assert/strict';
import {consumeQueryStream, httpFailure, queryFailure} from '../src/queryStream.js';

function response(chunks) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  }));
}
const bytes = text => new TextEncoder().encode(text);

test('UTF-8 byte splits, CRLF and multiline SSE data preserve the complete result', async () => {
  const text = ': heartbeat\r\n\r\ndata: {"type":"progress","step":"检索"}\r\n\r\n' +
    'data: {"type":"result",\r\ndata: "data":[{"国家":"法国"}]}\r\n\r\n';
  const events = [];
  await consumeQueryStream(response([...bytes(text)].map(byte => Uint8Array.of(byte))), event => events.push(event));
  assert.equal(events.length, 2);
  assert.deepEqual(events[1].data, [{国家: '法国'}]);
});

test('EOF before terminal is a visible failure, not an empty success', async () => {
  await assert.rejects(consumeQueryStream(response([bytes('data: {"type":"progress"}\n\n')]), () => {}), /提前中断/);
});

test('malformed JSON is rejected without leaking the raw body', async () => {
  await assert.rejects(consumeQueryStream(response([bytes('data: secret-upstream\n\n')]), () => {}), error => {
    assert.match(error.message, /格式异常/);
    assert.doesNotMatch(error.message, /secret/);
    return true;
  });
});

test('a result missing data is not accepted', async () => {
  await assert.rejects(consumeQueryStream(response([bytes('data: {"type":"result"}\n\n')]), () => {}), /缺少数据表/);
});

test('clarification and error are valid terminal events', async () => {
  for (const type of ['clarification', 'error']) {
    const events = [];
    await consumeQueryStream(response([bytes(`data: {"type":"${type}"}\n\n`)]), event => events.push(event));
    assert.equal(events[0].type, type);
  }
});

test('terminal releases the connection without waiting for server EOF', async () => {
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) { controller.enqueue(bytes('data: {"type":"result","data":[]}\n\n')); },
    cancel() { cancelled = true; },
  });
  await consumeQueryStream(new Response(stream), () => {});
  assert.equal(cancelled, true);
});

test('oversized unterminated frames are bounded', async () => {
  await assert.rejects(consumeQueryStream(response([bytes('x'.repeat(2 * 1024 * 1024 + 1))]), () => {}), /上限/);
});

test('missing body is reported', async () => {
  await assert.rejects(consumeQueryStream(new Response(null), () => {}), /未返回/);
});

test('401 distinguishes service token from model key; 429 is not called auth failure', () => {
  assert.match(httpFailure(401, 'a'.repeat(32)), /DATA_AGENT_API_TOKEN/);
  assert.match(httpFailure(401, 'a'.repeat(32)), /诊断编号/);
  assert.match(httpFailure(429), /频繁/);
  assert.doesNotMatch(httpFailure(503, 'private-token'), /private-token/);
});

test('upstream auth and client auth have different messages; only known diagnostics displayed', () => {
  assert.match(queryFailure({code: 'MODEL_AUTH'}), /服务端模型密钥/);
  assert.match(queryFailure({code: 'UPSTREAM_TIMEOUT', stage: 'column_embedding'}), /字段向量生成/);
  assert.doesNotMatch(queryFailure({code: 'private', stage: 'private', message: 'secret'}), /private|secret/);
});
