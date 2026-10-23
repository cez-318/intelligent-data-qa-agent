<template>
  <div class="chat-page">
    <!-- 消息区 -->
    <div ref="messagesEl" class="messages">
      <header class="demo-header">
        <h1>智能问数</h1>
        <p>大模型理解问题 · 字段、取值与指标检索 · 受控查询与结果分析</p>
        <p v-if="serviceStatus?.dataset"><strong>{{ serviceStatus.dataset.name }}</strong> · {{ serviceStatus.dataset.coverage }}<br />{{ serviceStatus.dataset.notice }}</p>
        <p v-if="serviceStatus?.ready">依赖检查通过，查询将使用配置的数据源；模型可用性以实际查询为准。</p>
        <p v-else class="service-warning">服务未就绪。{{ serviceStatus?.missing_configuration?.length ? '待配置：' + serviceStatus.missing_configuration.join('、') : '请检查数据库、模型与检索服务。' }} 不会切换为规则演示。</p>
        <button @click="refreshStatus">刷新服务状态</button>
        <div class="examples"><button v-for="example in examples" :key="example" :disabled="loading" @click="question = example; sendQuestion()">{{ example }}</button></div>
        <details open><summary>服务访问凭据</summary><input v-model="apiToken" type="password" autocomplete="off" placeholder="仅保存在当前页面内存" aria-label="服务访问凭据" /></details>
      </header>
      <ExperimentPanel :api-token="apiToken" :catalog="serviceStatus?.experiments || []" />
      <div
          v-for="(msg, index) in messages"
          :key="index"
          :class="['message-row', msg.role]"
      >
        <div v-if="msg.role === 'assistant'" class="avatar">🤖</div>

        <div class="bubble">
          <!-- 文本 -->
          <div v-if="msg.type === 'text'">
            {{ msg.content }}
          </div>

          <!-- 进度步骤 -->
          <div v-else-if="msg.type === 'steps'" class="steps">
            <div v-for="(step, sIdx) in msg.steps" :key="sIdx" class="step">
              <span class="dot" :class="step.status"></span>
              <span>{{ step.text }}</span>
            </div>
          </div>

          <!-- 表格 -->
          <div v-else-if="msg.type === 'table'" class="table-wrap">
            <p>{{ msg.summary }}</p>
            <p v-if="!msg.rows.length">未找到数据，不解释为零。</p>
            <p v-if="msg.evidence?.possibly_truncated" class="service-warning">结果可能达到行数上限；排名或对比仅涵盖已返回的分组。</p>
            <section v-if="msg.decomposition" class="decomposition-card">
              <h3>变化贡献分解 · 非因果分析</h3>
              <template v-if="msg.decomposition.status === 'complete'">
                <p>当前期：{{ formatMeasure(msg.decomposition.current) }} · 基期：{{ formatMeasure(msg.decomposition.previous) }} · 变化：{{ formatMeasure(msg.decomposition.difference) }}</p>
                <p v-if="msg.decomposition.remainder">其余 {{ msg.decomposition.remainder.group_count }} 个分组的合计变化：{{ formatMeasure(msg.decomposition.remainder.difference) }}；完整分组数：{{ msg.decomposition.group_count }}。</p>
                <p>分解核对残差：{{ formatMeasure(msg.decomposition.reconciliation_residual) }}</p>
                <p>{{ msg.decomposition.note }}</p>
              </template>
              <p v-else>条件不足，未生成贡献结论。</p>
              <details><summary>查看分解方法与完整依据</summary><pre>{{ JSON.stringify(msg.decomposition, null, 2) }}</pre></details>
            </section>
            <pre v-if="msg.analysis">对比结果：{{ JSON.stringify(msg.analysis, null, 2) }}</pre>
            <details v-if="msg.evidence"><summary>查看指标口径与查询依据</summary><pre>{{ JSON.stringify(msg.evidence, null, 2) }}</pre></details>
            <table class="result-table">
              <thead>
              <tr>
                <th v-for="col in msg.columns" :key="col">
                  {{ col }}
                </th>
              </tr>
              </thead>
              <tbody>
              <tr v-for="(row, rIdx) in msg.rows" :key="rIdx">
                <td v-for="col in msg.columns" :key="col">
                  {{ displayCell(col, row[col]) }}
                </td>
              </tr>
              </tbody>
            </table>
          </div>

          <!-- 错误 -->
          <div v-else-if="msg.type === 'error'" class="error-text">
            {{ msg.content }}
          </div>
        </div>

        <div v-if="msg.role === 'user'" class="avatar">🧑</div>
      </div>
      <div class="messages-bottom-spacer"></div>
    </div>

    <!-- 悬浮输入框 -->
    <div class="input-wrapper">
      <div class="input-box">
        <input
            v-model="question"
            @keyup.enter="sendQuestion"
            placeholder="请描述指标、时间范围和筛选条件"
            aria-label="问数问题"
            maxlength="2000"
        />
        <button @click="sendQuestion" :disabled="loading">
          {{ loading ? "执行中..." : "发送" }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import {nextTick, ref, onMounted, computed} from "vue";
import ExperimentPanel from './ExperimentPanel.vue';
import {consumeQueryStream, httpFailure, queryFailure, traceSuffix} from './queryStream.js';

const API_URL = "/api/query";

const question = ref("");
const apiToken = ref("");
const serviceStatus = ref(null);
const examples = computed(() => serviceStatus.value?.dataset?.examples || []);
async function refreshStatus() {
  try { serviceStatus.value = await (await fetch('/api/health')).json(); }
  catch { serviceStatus.value = {ready: false}; }
}
onMounted(refreshStatus);
const loading = ref(false);
const messages = ref([]);
const messagesEl = ref(null);
function formatMeasure(value) {
  if (value === null || value === undefined) return '未定义';
  const numeric = Number(value);
  return Number.isFinite(numeric) ? new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 4}).format(numeric) : value;
}
function displayCell(column, value) {
  if (['current', 'previous', 'difference', 'contribution_percent'].includes(column)) return formatMeasure(value);
  return value;
}

function scrollToBottom() {
  const el = messagesEl.value;
  if (!el) return;
  el.scrollTop = el.scrollHeight;
}

async function sendQuestion() {
  if (!question.value || loading.value) return;
  if (!apiToken.value.trim()) {
    messages.value.push({role: 'assistant', type: 'error', content: '请先在上方填写 DATA_AGENT_API_TOKEN（服务访问令牌，不是 DeepSeek API 密钥）。刷新页面后需要重新填写。'});
    return;
  }
  if (!serviceStatus.value?.ready) {
    messages.value.push({role: 'assistant', type: 'error', content: '服务未就绪，请先完成配置并重启服务。'});
    return;
  }

  const q = question.value;
  question.value = "";
  loading.value = true;

  messages.value.push({role: "user", type: "text", content: q});

  // steps 容器
  const stepIndex =
      messages.value.push({
        role: "assistant",
        type: "steps",
        steps: [],
      }) - 1;

  await nextTick();
  scrollToBottom();

  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), 70000);
  let requestId = '';
  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: {"Content-Type": "application/json", Authorization: `Bearer ${apiToken.value.trim()}`},
      body: JSON.stringify({query: q}),
      signal: controller.signal,
    });

    requestId = response.headers.get('X-Request-ID') || '';
    if (!response.ok) throw new Error(httpFailure(response.status));
    await consumeQueryStream(response, async (data) => {
        const steps = messages.value[stepIndex].steps;

        // ✅ progress：完全按后端状态渲染
        if (data.type === "progress") {
          let step = steps.find((s) => s.text === data.step);

          if (!step) {
            step = {
              text: data.step,
              status: data.status,
            };
            steps.push(step);
          } else {
            step.status = data.status;
          }
        }

        // ✅ 表格结果
        else if (data.type === "result" && Array.isArray(data.data)) {
          messages.value.push({
            role: "assistant",
            type: "table",
            columns: Object.keys(data.data[0] || {}),
            rows: data.data,
            summary: data.summary,
            analysis: data.analysis,
            evidence: data.evidence,
            decomposition: data.decomposition,
          });
        }

        // ✅ 错误
        else if (data.type === "error" || data.type === "clarification") {
          messages.value.push({
            role: "assistant",
            type: "error",
            content: data.type === 'error' ? queryFailure(data, requestId) : (data.message || '请补充查询条件。'),
          });
        }

        await nextTick();
        scrollToBottom();
    });
  } catch (e) {
    messages.value.push({
      role: "assistant",
      type: "error",
      content: (controller.signal.aborted ? '请求等待超时，已停止接收，请稍后重试。' : (e?.message || '请求失败')) + traceSuffix(requestId),
    });
  } finally {
    clearTimeout(deadline);
    for (const step of messages.value[stepIndex].steps) {
      if (step.status === 'running') step.status = 'error';
    }
    loading.value = false;
    await nextTick();
    scrollToBottom();
  }
}
</script>
<style scoped>
/* 覆盖 Vite 默认居中 */
:global(html),
:global(body) {
  height: 100%;
  margin: 0;
}

:global(body) {
  display: block !important;
  place-items: unset !important;
}

:global(#app) {
  height: 100%;
  max-width: none !important;
  margin: 0 !important;
  padding: 0 !important;
}

/* 页面 */
.chat-page {
  height: 100%;
  overflow: hidden;
  background: #fff;
}

/* 消息区 */
.messages {
  height: 100%;
  box-sizing: border-box;
  overflow-y: auto;
  padding: 20px 20% 160px;
}

.message-row {
  display: flex;
  margin-bottom: 14px;
}

.demo-header { margin-bottom: 28px; color: #25334a; }
.demo-header h1 { font-size: 24px; }
.demo-header p { font-size: 14px; line-height: 1.6; }
.service-warning { color: #a14515; background: #fff7ed; padding: 10px; border-radius: 8px; }
.decomposition-card { padding: 14px; margin: 12px 0; border: 1px solid #b9cfe6; border-radius: 10px; background: #f0f7ff; }
.decomposition-card h3 { margin: 0 0 8px; font-size: 16px; }
.decomposition-card p { font-size: 13px; line-height: 1.6; }
.examples { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.examples button { border: 1px solid #b9cfe6; border-radius: 8px; padding: 8px; background: #f0f7ff; color: #19497c; cursor: pointer; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
@media (max-width: 900px) { .messages { padding-left: 10px; padding-right: 10px; } .bubble { max-width: 90%; } }

.message-row.assistant {
  justify-content: flex-start;
}

.message-row.user {
  justify-content: flex-end;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 10px;
}

.bubble {
  max-width: min(820px, 72%);
  padding: 12px 14px;
  border-radius: 12px;
  background: #f5f5f5;
}

.message-row.user .bubble {
  background: #e6f4ff;
}

/* 步骤 */
.steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.step {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot.running {
  background: #f1c40f;
}

.dot.success {
  background: #2ecc71;
}

.dot.error {
  background: #e74c3c;
}

/* 表格 */
.table-wrap {
  max-width: 100%;
  overflow-x: auto;
}

.result-table {
  width: max-content;
  min-width: 100%;
  table-layout: auto;
  border-collapse: collapse;
}

.result-table th,
.result-table td {
  border: 1px solid #ddd;
  padding: 6px 12px;
  white-space: nowrap;
  font-size: 13px;
  text-align: left;
}

.result-table th {
  background: #fafafa;
  font-weight: 600;
  position: sticky;
  top: 0;
  z-index: 1;
}

/* 错误 */
.error-text {
  color: #e74c3c;
  font-weight: 600;
}

/* 悬浮输入框 */
.input-wrapper {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 24px;
  display: flex;
  justify-content: center;
  padding: 0 16px;
  pointer-events: none;
}

.input-box {
  pointer-events: auto;
  width: 100%;
  max-width: 720px;
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(0, 0, 0, 0.08);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12);
}

.input-box input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
}

.input-box button {
  padding: 8px 18px;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, #409eff, #66b1ff);
  color: #fff;
  cursor: pointer;
}

.input-box button:disabled {
  opacity: 0.5;
}

.messages-bottom-spacer {
  height: 200px;
}
</style>
