const STAGES = {
  expand_columns: '字段检索词生成', expand_values: '取值检索词生成', expand_metrics: '指标检索词生成',
  column_embedding: '字段向量生成', metric_embedding: '指标向量生成',
  column_search: '字段检索', metric_search: '指标检索', value_search: '取值检索',
  select_columns: '字段筛选', select_metrics: '指标筛选', plan_query: '查询规划', repair_intent: '条件修复',
};

export function traceSuffix(id) {
  return /^[a-f0-9]{32}$/.test(id || '') ? ` 诊断编号：${id}` : '';
}

export function httpFailure(status, id) {
  const messages = {
    401: '服务访问令牌无效，请填写 DATA_AGENT_API_TOKEN，而不是 DeepSeek API 密钥。',
    403: '当前访问未获授权，请联系维护者。',
    422: '问题格式不符合要求，请检查输入长度和内容。',
    429: '请求过于频繁，请稍后重试。',
    503: '服务尚未就绪，请检查数据库与检索依赖并刷新服务状态。',
  };
  return (messages[status] || `请求未完成（${status}），请稍后重试。`) + traceSuffix(id);
}

export function queryFailure(event, id) {
  const messages = {
    TIMEOUT: '查询超时，请缩小问题范围或稍后重试。',
    UPSTREAM_TIMEOUT: '模型或检索服务响应超时，请稍后重试。',
    UPSTREAM_CONNECTION: '检索依赖连接失败，请联系维护者检查服务。',
    UPSTREAM_UNAVAILABLE: '检索依赖暂时不可用，请稍后重试。',
    UPSTREAM_RATE_LIMIT: '上游服务限流，请稍后重试。',
    MODEL_AUTH: '大模型认证失败，请维护者检查服务端模型密钥。',
    UPSTREAM_AUTH: '检索依赖认证失败，请联系维护者；无需更换页面访问令牌。',
    MODEL_CONNECTION: '大模型连接失败，请稍后重试。',
  };
  const stage = STAGES[event.stage];
  return (messages[event.code] || '查询未完成，请联系维护者查看诊断记录。') +
    (stage ? ` 失败阶段：${stage}。` : '') + traceSuffix(event.request_id || id);
}

// The stream must end in a result, clarification or error. A disconnected HTTP
// 200 must never look like a successful empty answer.
export async function consumeQueryStream(response, onEvent) {
  if (!response.body) throw new Error('服务器未返回结果流。');
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', {fatal: true});
  let buffer = '';
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) throw new Error('结果流提前中断，未收到完整结果，请重试。');
      buffer += decoder.decode(value, {stream: true});
      if (buffer.length > 2 * 1024 * 1024) throw new Error('结果流超出页面处理上限。');
      let separator;
      while ((separator = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).replace(/^ /, '')).join('\n');
        if (!data) continue;
        let event;
        try { event = JSON.parse(data); }
        catch { throw new Error('服务器结果流格式异常，请联系维护者。'); }
        if (!event || typeof event !== 'object' || Array.isArray(event)) {
          throw new Error('服务器结果流格式异常，请联系维护者。');
        }
        const terminal = ['result', 'clarification', 'error'].includes(event.type);
        if (event.type === 'result' && !Array.isArray(event.data)) {
          throw new Error('服务器结果缺少数据表，请联系维护者。');
        }
        await onEvent(event);
        if (terminal) return;
      }
    }
  } finally {
    try { await reader.cancel(); } catch { /* The connection may already be closed. */ }
    reader.releaseLock();
  }
}
