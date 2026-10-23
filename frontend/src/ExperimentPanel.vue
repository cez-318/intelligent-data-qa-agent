<template>
  <section class="experiment-panel" aria-label="随机实验评估">
    <h2>随机实验评估</h2>
    <p>独立于零售问数：只评估已登记的随机实验，不让大模型编造干预、对照组或效应值。</p>
    <label>选择已登记实验
      <select v-model="selected" :disabled="busy" aria-label="选择已登记实验">
        <option value="">请选择</option>
        <option v-for="item in catalog" :key="item.id" :value="item.id">{{ item.title }}</option>
      </select>
    </label>
    <button @click="evaluate" :disabled="busy || !selected">{{ busy ? '核对数据与计算中…' : '核对实验并估计效应' }}</button>
    <p v-if="error" role="alert" class="warning">{{ error }}</p>
    <article v-if="result" aria-live="polite">
      <h3>{{ result.title }}</h3>
      <p>{{ result.evidence.window }}。{{ result.evidence.population }}。</p>
      <p v-if="result.status !== 'complete'" class="warning">实验未通过样本分配比例检查，停止输出效应结论。请先核对分组与数据完整性。</p>
      <template v-else>
        <p><strong>条件性实验效应估计，不是任意业务因果发现。</strong>{{ result.interpretation }}</p>
        <p>全部 {{ result.comparison_count }} 项比较统一作 Bonferroni 校正；每项区间 {{ number(result.interval_level * 100) }}%，整体名义覆盖目标 {{ number(result.family_confidence * 100) }}%。</p>
        <div class="scroll-table">
          <table>
            <caption>相对不发邮件对照组 · 效应单位为百分点（不是相对增长百分比）</caption>
            <thead><tr><th>邮件方案</th><th>指标</th><th>处理/对照人数</th><th>处理/对照率</th><th>效应（百分点）</th><th>校正区间（百分点）</th><th>证据方向</th></tr></thead>
            <tbody><tr v-for="row in result.effects" :key="row.treatment + row.outcome">
              <td>{{ armName(row.treatment) }}</td><td>{{ row.outcome_label }}</td>
              <td>{{ row.treatment_n }} / {{ row.control_n }}</td>
              <td>{{ number(row.treatment_rate * 100) }}% / {{ number(row.control_rate * 100) }}%</td>
              <td>{{ number(row.effect_percentage_points) }}</td>
              <td>[{{ number(row.ci_low_percentage_points) }}, {{ number(row.ci_high_percentage_points) }}]</td>
              <td>{{ direction(row.direction) }}</td>
            </tr></tbody>
          </table>
        </div>
        <p v-for="item in result.limitations" :key="item" class="caveat">{{ item }}</p>
      </template>
      <p>数据 {{ result.data_quality.rows.toLocaleString() }} 行；未排除记录。完全相同行的额外数量 {{ result.data_quality.exact_duplicate_extra_rows.toLocaleString() }}。{{ result.data_quality.duplicate_policy }}</p>
      <p>分配比例检查 p={{ number(result.diagnostics.sample_ratio_p) }}；通过不代表已证明随机化正确。</p>
      <p v-if="result.data_quality.baseline_balance.some(row => row.flag)" class="warning">部分处理前变量有明显不平衡，需检查实验设计与数据。</p>
      <details><summary>数据来源、基线平衡与完整计算依据</summary><pre>{{ JSON.stringify(result, null, 2) }}</pre></details>
      <button @click="download">导出本次评估 JSON</button>
    </article>
  </section>
</template>

<script setup>
import {ref} from 'vue';
const props = defineProps({apiToken: {type:String,default:''}, catalog: {type:Array,default:()=>[]}});
const selected=ref(''), busy=ref(false), error=ref(''), result=ref(null);
const number = value => new Intl.NumberFormat('zh-CN',{maximumFractionDigits:4}).format(value);
const armName = value => ({'Mens E-Mail':'男装主题邮件','Womens E-Mail':'女装主题邮件','No E-Mail':'不发邮件'}[value] || value);
const direction = value => ({positive:'区间完全大于0',negative:'区间完全小于0',inconclusive:'区间包含0，证据不足'}[value]);
async function evaluate() {
  if (busy.value || !selected.value) return;
  result.value=null;
  error.value='';
  if (!props.apiToken.trim()) {error.value='请先在上方填写服务访问令牌（不是 DeepSeek 密钥）。'; return;}
  busy.value=true;
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),30000);
  try {
    const response=await fetch('/api/experiments/evaluate',{method:'POST',
      headers:{'Content-Type':'application/json',Authorization:`Bearer ${props.apiToken.trim()}`},
      body:JSON.stringify({experiment_id:selected.value}),signal:controller.signal});
    const data=await response.json();
    if (!response.ok) throw new Error(data.detail?.message || `实验请求失败（${response.status}），请检查访问令牌及登记数据。`);
    result.value=data;
  } catch (e) {error.value=e.name==='AbortError'?'计算超时，未输出实验结论。':e.message;}
  finally {clearTimeout(timeout); busy.value=false;}
}
function download() {
  const link=document.createElement('a');
  const url=URL.createObjectURL(new Blob([JSON.stringify(result.value,null,2)],{type:'application/json'}));
  link.href=url; link.download=`${result.value.experiment_id}_evaluation.json`; link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
</script>

<style scoped>
.experiment-panel{border:1px solid #b9cfe6;border-radius:12px;padding:18px;margin:20px 0;background:#f8fbff;color:#25334a}
h2{font-size:19px;margin-top:0}h3{font-size:16px}p{font-size:13px;line-height:1.7}label{display:block;font-size:14px}
select{display:block;width:100%;padding:10px;margin:8px 0;box-sizing:border-box;background:white;color:#25334a;border:1px solid #8194aa;border-radius:6px}
button{padding:9px 14px;background:#19497c;color:white;border:0;border-radius:6px;cursor:pointer}button:disabled{opacity:.55;cursor:default}
.scroll-table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px}caption{text-align:left;padding:10px 0;line-height:1.6}
th,td{text-align:left;border:1px solid #ccd6e0;padding:9px;white-space:nowrap}th{background:#e9f1fa}
.warning{background:#fff2df;color:#8a3500;padding:10px}.caveat{color:#4a5667}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
details{margin:14px 0}summary{cursor:pointer}button:focus-visible,select:focus-visible{outline:3px solid #2b78d4;outline-offset:3px}
</style>
