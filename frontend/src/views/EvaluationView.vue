<template>
  <div class="eval-view">
    <el-card class="header-card">
      <h2>评估中心</h2>
      <p class="subtitle">对比不同 Retrieval / Rerank / Generation 模型效果（KB 由数据集绑定，embedding 用 KB 上传时的）</p>
    </el-card>

    <el-tabs v-model="activeTab" type="border-card">
      <!-- ====== 新建评估 ====== -->
      <el-tab-pane label="新建评估" name="create">
        <el-form :model="form" label-width="140px" style="max-width: 800px">
          <el-form-item label="评估名称">
            <el-input v-model="form.name" placeholder="例如：test01" />
          </el-form-item>

          <el-form-item label="数据集">
            <div style="display: flex; gap: 10px; width: 100%">
              <el-select v-model="form.dataset_id" placeholder="选择已有数据集" style="flex: 1" clearable>
                <el-option v-for="d in datasets" :key="d.id" :label="`${d.name} (${d.qa_count}题)`" :value="d.id" />
              </el-select>
              <el-button @click="showCreateDataset = true" type="primary" plain>
                自动生成
              </el-button>
            </div>
          </el-form-item>

          <el-form-item label="评估用 QA 数量">
            <el-input-number v-model="form.qa_sample_size" :min="1" :max="500" />
            <span style="margin-left: 10px; color: #999">
              留空或 &gt; 数据集大小 = 全部；从 dataset 中取前 N 个
            </span>
          </el-form-item>

          <el-form-item label="并行度">
            <el-slider v-model="form.concurrency" :min="1" :max="8" show-stops :marks="concurrencyMarks" />
          </el-form-item>

          <el-form-item label="Retrieval 策略">
            <el-checkbox-group v-model="form.retrieval_strategies" @change="onRetrievalChange">
              <el-checkbox v-for="s in retrievalOptions" :key="s.key" :label="s.key">
                {{ s.label }}
              </el-checkbox>
            </el-checkbox-group>
          </el-form-item>

          <el-form-item v-if="form.retrieval_strategies.includes('rerank')" label="Rerank 模型">
            <el-checkbox-group v-model="form.rerank_models">
              <el-checkbox v-for="m in models.reranks || []" :key="m.id" :label="m.id">
                {{ m.id }} <el-tag size="small" :type="m.type === 'local' ? 'success' : 'warning'">{{ m.type }}</el-tag>
              </el-checkbox>
            </el-checkbox-group>
          </el-form-item>

          <el-form-item label="Generation 模型">
            <el-checkbox-group v-model="form.generation_models">
              <el-checkbox v-for="m in models.llms || []" :key="m.id" :label="m.id">
                {{ m.id }} <el-tag size="small" :type="m.type === 'local' ? 'success' : 'warning'">{{ m.type }}</el-tag>
              </el-checkbox>
            </el-checkbox-group>
          </el-form-item>

          <el-form-item label="评估指标（8 个，可手动开关）">
            <div style="display: flex; flex-direction: column; gap: 8px">
              <div>
                <span style="color: #666; margin-right: 8px">检索（5）：</span>
                <el-checkbox-group v-model="form.enabled_metrics">
                  <el-checkbox
                    v-for="m in retrievalMetricOptions"
                    :key="m.key"
                    :label="m.key"
                    :disabled="!canToggleMetrics"
                  >
                    {{ m.label }}
                  </el-checkbox>
                </el-checkbox-group>
              </div>
              <div>
                <span style="color: #666; margin-right: 8px">LLM（3）：</span>
                <el-checkbox-group v-model="form.enabled_metrics">
                  <el-checkbox
                    v-for="m in llmMetricOptions"
                    :key="m.key"
                    :label="m.key"
                    :disabled="!canToggleMetrics"
                  >
                    {{ m.label }}
                  </el-checkbox>
                </el-checkbox-group>
              </div>
            </div>
            <div style="margin-top: 8px; display: flex; gap: 8px">
              <el-button size="small" @click="selectAllMetrics" :disabled="!canToggleMetrics">全选</el-button>
              <el-button size="small" @click="selectNoMetrics" :disabled="!canToggleMetrics">全不选</el-button>
              <el-button size="small" type="primary" plain @click="resetToDefaultMetrics" :disabled="!canToggleMetrics">
                恢复默认（全开）
              </el-button>
              <span style="color: #999; align-self: center; margin-left: 8px">
                当前已选 {{ form.enabled_metrics.length }} / {{ allMetricOptions.length }} 个
              </span>
            </div>
          </el-form-item>

          <el-form-item label="LLM 评估模型">
            <el-select
              v-model="form.llm_metric_model"
              placeholder="默认 mimo-v2.5"
              style="width: 280px"
              allow-create
              filterable
              clearable
            >
              <el-option
                v-for="m in llmMetricModelOptions"
                :key="m"
                :label="m"
                :value="m"
              />
            </el-select>
            <span style="margin-left: 10px; color: #999">
              默认 settings.MIMO_MODEL，可在启动时覆盖
            </span>
          </el-form-item>

          <el-form-item>
            <el-button type="primary" @click="startRun" :loading="starting" :disabled="!canStart">
              启动评估
            </el-button>
            <el-button @click="resetForm">重置</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <!-- ====== 历史运行 ====== -->
      <el-tab-pane label="历史运行" name="history">
        <el-table :data="runs" v-loading="loadingRuns">
          <el-table-column prop="name" label="名称" width="180" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="240">
            <template #default="{ row }">
              <el-progress
                :percentage="row.progress"
                :status="row.status === 'failed' ? 'exception' : (row.status === 'completed' ? 'success' : '')"
              />
              <span style="margin-left: 8px; font-size: 12px; color: #999">
                {{ row.completed_tasks }}/{{ row.total_tasks }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="started_at" label="开始时间" width="180">
            <template #default="{ row }">
              {{ row.started_at ? new Date(row.started_at).toLocaleString() : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="resume_count" label="续跑次数" width="80" />
          <el-table-column label="操作" width="320">
            <template #default="{ row }">
              <el-button v-if="row.status === 'running'" size="small" type="warning" @click="stopRun(row)">
                停止
              </el-button>
              <el-button v-if="['stopped','failed'].includes(row.status)" size="small" type="primary" @click="resumeRun(row)">
                续跑
              </el-button>
              <el-button v-if="row.status === 'completed'" size="small" @click="viewReport(row)">
                查看报告
              </el-button>
              <el-button size="small" type="danger" @click="deleteRunConfirm(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ====== 数据集管理 ====== -->
      <el-tab-pane label="数据集管理" name="datasets">
        <el-table :data="datasets" v-loading="loadingDatasets">
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="kb_id" label="KB ID" width="80" />
          <el-table-column prop="qa_count" label="题数" width="80" />
          <el-table-column prop="created_at" label="创建时间" width="180">
            <template #default="{ row }">
              {{ new Date(row.created_at).toLocaleString() }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button size="small" @click="viewDataset(row)">查看</el-button>
              <el-button size="small" type="danger" @click="deleteDatasetConfirm(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- ====== 报告弹窗 ====== -->
    <el-dialog v-model="reportDialog" title="评估报告" width="900px">
      <div v-if="reportData">
        <h3>{{ reportData.name }}</h3>
        <p>状态：<el-tag>{{ reportData.status }}</el-tag></p>
        <p>任务：{{ reportData.completed_tasks }} / {{ reportData.total_tasks }}</p>
        <h4>配置</h4>
        <ul>
          <li>KB (embedding): {{ reportKBLabel || '（数据集绑定）' }}</li>
          <li>Retrieval: {{ reportEnabledRetrievalLabels }}</li>
          <li v-if="reportData.config.rerank_models?.length">Rerank: {{ reportData.config.rerank_models.join(', ') }}</li>
          <li>Generation: {{ reportData.config.generation_models?.join(', ') }}</li>
          <li>LLM 评估模型: {{ reportData.config.llm_metric_model || 'mimo-v2.5' }}</li>
          <li>
            启用的指标（{{ reportEnabledCount }} / {{ allMetricOptions.length }}）：
            {{ reportEnabledLabels || '无' }}
          </li>
        </ul>
        <h4>Summary</h4>
        <pre style="background: #f5f5f5; padding: 12px; border-radius: 4px; max-height: 400px; overflow: auto;">{{ JSON.stringify(reportData.summary, null, 2) }}</pre>

        <h4>报告文件</h4>
        <p>JSON: <code>{{ reportData.report_json_path }}</code></p>
        <p>MD: <code>{{ reportData.report_md_path }}</code></p>
      </div>
    </el-dialog>

    <!-- ====== 创建数据集弹窗 ====== -->
    <el-dialog v-model="showCreateDataset" title="自动生成数据集" width="480px">
      <el-form :model="datasetForm" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="datasetForm.name" placeholder="例如：test-dataset-1" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="datasetForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="QA 数量">
          <el-input-number v-model="datasetForm.n_questions" :min="1" :max="200" />
        </el-form-item>
        <el-form-item label="使用 KB">
          <el-select v-model="datasetForm.kb_id" style="width: 100%">
            <el-option v-for="kb in kbs" :key="kb.id" :label="`${kb.name} · ${kb.embedding_model || '未知 embedding'}`" :value="kb.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDataset = false">取消</el-button>
        <el-button type="primary" @click="createDataset" :loading="creating">生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { evalAPI, kbAPI } from '../api'

const activeTab = ref('create')

// Models
const models = ref({ embeddings: [], reranks: [], llms: [] })
const kbs = ref([])
const datasets = ref([])
const runs = ref([])

// Form
const ALL_METRIC_KEYS = [
  'recall_at_k', 'precision_at_k', 'hit_at_k', 'mrr', 'ndcg_at_k',
  'faithfulness', 'answer_relevancy', 'answer_correctness',
]
const METRIC_LABELS = {
  recall_at_k: 'Recall@K',
  precision_at_k: 'Precision@K',
  hit_at_k: 'Hit@K',
  mrr: 'MRR',
  ndcg_at_k: 'NDCG@K',
  faithfulness: 'Faithfulness',
  answer_relevancy: 'Answer Relevancy',
  answer_correctness: 'Answer Correctness',
}
const allMetricOptions = ALL_METRIC_KEYS.map(k => ({ key: k, label: METRIC_LABELS[k] || k }))
const retrievalMetricOptions = allMetricOptions.filter(m =>
  ['recall_at_k', 'precision_at_k', 'hit_at_k', 'mrr', 'ndcg_at_k'].includes(m.key)
)
const llmMetricOptions = allMetricOptions.filter(m =>
  ['faithfulness', 'answer_relevancy', 'answer_correctness'].includes(m.key)
)

const form = ref({
  name: '',
  dataset_id: null,
  // 评估用 QA 数量：null = 全部（取 dataset 所有 QA）；设值 = 取前 N 个
  qa_sample_size: null,
  concurrency: 4,
  retrieval_strategies: ['vector'],
  rerank_models: ['BAAI/bge-reranker-base'],
  generation_models: ['mimo-v2.5-pro'],
  // 默认 8 个指标全开
  enabled_metrics: [...ALL_METRIC_KEYS],
  // LLM 评估模型默认 mimo-v2.5（即 settings.MIMO_MODEL，可在启动时覆盖）
  llm_metric_model: 'mimo-v2.5',
})

// LLM 评估模型下拉选项（用户可手输任意名字；'mimo-lite' 已废弃，下拉不再提供）
const llmMetricModelOptions = ['mimo-v2.5', 'mimo-v2.5-pro']

const canToggleMetrics = computed(() => !starting.value)
const selectAllMetrics = () => { form.value.enabled_metrics = [...ALL_METRIC_KEYS] }
const selectNoMetrics = () => { form.value.enabled_metrics = [] }
const resetToDefaultMetrics = () => { form.value.enabled_metrics = [...ALL_METRIC_KEYS] }

const concurrencyMarks = { 1: '1', 2: '2', 4: '4', 6: '6', 8: '8' }
// 检索策略选项：key 给后端，label 给 UI
//   "vector" → "Vector（向量检索）"
//   "hybrid" → "Hybrid Fusion（混合检索 · vector + BM25 加权融合）"
//   "rerank" → "Vector 初筛 + Rerank 重排"
const retrievalOptions = [
  { key: 'vector', label: 'Vector（向量检索）' },
  { key: 'hybrid', label: 'Hybrid Fusion（混合检索 · vector + BM25 加权融合）' },
  { key: 'rerank', label: 'Vector 初筛 + Rerank 重排' },
]

// Dataset form
const showCreateDataset = ref(false)
const datasetForm = ref({
  name: '',
  description: '',
  n_questions: 20,
  kb_id: null,
})

const starting = ref(false)
const creating = ref(false)
const loadingDatasets = ref(false)
const loadingRuns = ref(false)

const canStart = computed(() => {
  return form.value.name && form.value.dataset_id
    && form.value.retrieval_strategies.length && form.value.generation_models.length
    && form.value.enabled_metrics.length > 0
})

const statusType = (s) => ({
  pending: 'info', running: 'warning', stopped: '',
  completed: 'success', failed: 'danger',
}[s] || '')

onMounted(async () => {
  await loadModels()
  await loadKBs()
  await loadDatasets()
  await loadRuns()
  startPolling()
})

let pollTimer = null
const startPolling = () => {
  pollTimer = setInterval(async () => {
    const hasRunning = runs.value.some(r => r.status === 'running')
    if (hasRunning || activeTab.value === 'history') {
      await loadRuns()
    }
  }, 2000)
}

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

const loadModels = async () => {
  const { data } = await evalAPI.getModels()
  models.value = data
}

const loadKBs = async () => {
  const { data } = await kbAPI.list()
  kbs.value = data
}

const loadDatasets = async () => {
  loadingDatasets.value = true
  try {
    const { data } = await evalAPI.listDatasets()
    datasets.value = data
  } finally {
    loadingDatasets.value = false
  }
}

const loadRuns = async () => {
  if (loadingRuns.value) return
  loadingRuns.value = true
  try {
    const { data } = await evalAPI.listRuns()
    runs.value = data
  } finally {
    loadingRuns.value = false
  }
}

const onRetrievalChange = () => {}

const startRun = async () => {
  starting.value = true
  try {
    await evalAPI.createRun({
      name: form.value.name,
      dataset_id: form.value.dataset_id,
      // 评估用 QA 数量（null = 全部；传数字 = 取前 N 个）
      qa_sample_size: form.value.qa_sample_size || null,
      retrieval_strategies: form.value.retrieval_strategies,
      rerank_models: form.value.retrieval_strategies.includes('rerank') ? form.value.rerank_models : [],
      generation_models: form.value.generation_models,
      concurrency: form.value.concurrency,
      // 关键：这两个字段上轮 commit 漏了，导致 judge LLM 兜底走 settings.MIMO_MODEL
      enabled_metrics: form.value.enabled_metrics,
      llm_metric_model: form.value.llm_metric_model || null,
    })
    ElMessage.success('评估已启动')
    activeTab.value = 'history'
    await loadRuns()
  } catch (e) {
    // axios 拦截器已处理
  } finally {
    starting.value = false
  }
}

const stopRun = async (row) => {
  await ElMessageBox.confirm(`确定停止评估 "${row.name}"？已完成结果将保留。`, '确认', { type: 'warning' })
  await evalAPI.stopRun(row.id)
  ElMessage.success('已发送停止信号')
  await loadRuns()
}

const resumeRun = async (row) => {
  await evalAPI.resumeRun(row.id)
  ElMessage.success('已续跑')
  await loadRuns()
}

const reportDialog = ref(false)
const reportData = ref(null)

// 报告弹窗：实际启用的指标（从 run.config.enabled_metrics 读）
// 老 run 没字段 → 默认全开
const reportEnabledKeys = computed(() => {
  const v = reportData.value?.config?.enabled_metrics
  if (Array.isArray(v) && v.length) return v
  return [...ALL_METRIC_KEYS]
})
const reportEnabledLabels = computed(() =>
  reportEnabledKeys.value.map(k => METRIC_LABELS[k] || k).join(', ')
)
const reportEnabledCount = computed(() => reportEnabledKeys.value.length)

// 报告弹窗：把 retrieval strategy key 翻译成 UI label
const reportEnabledRetrievalLabels = computed(() => {
  const keys = reportData.value?.config?.retrieval_strategies || []
  return keys.map(k => retrievalOptions.find(o => o.key === k)?.label || k).join(', ')
})

// 报告弹窗：把 dataset.kb_id 翻译成 "KB name · embedding_model" 格式
// 兼容老 run：优先用 config.embedding_models[0] 派生（kb_ids 已删除）
const reportKBLabel = computed(() => {
  const cfg = reportData.value?.config
  if (!cfg) return ''
  // 优先用 config.embedding_models（老 run 有这个字段）
  const ems = cfg.embedding_models
  if (Array.isArray(ems) && ems.length) {
    // 找匹配 em 的 KB
    const matched = kbs.value.find(kb => ems.includes(kb.embedding_model))
    if (matched) return `${matched.name} · ${matched.embedding_model}`
    // 没匹配上 KB，只显示 em
    return ems.join(', ')
  }
  return ''
})

const viewReport = async (row) => {
  const { data } = await evalAPI.getRun(row.id)
  reportData.value = data
  reportDialog.value = true
}

const deleteRunConfirm = async (row) => {
  await ElMessageBox.confirm(
    `确定删除评估 "${row.name}"？数据库记录和报告文件都会永久删除。`,
    '危险操作',
    { type: 'error' }
  )
  await evalAPI.deleteRun(row.id)
  ElMessage.success('已删除')
  await loadRuns()
}

const viewDataset = async (row) => {
  const { data } = await evalAPI.getDataset(row.id)
  ElMessageBox.alert(
    `题目数：${data.qa_count}\n\n前 3 题示例：\n` +
    data.qa_pairs.slice(0, 3).map((q, i) => `${i+1}. Q: ${q.question}\n   A: ${q.ground_truth}`).join('\n\n'),
    `数据集：${data.name}`,
    { confirmButtonText: '关闭' }
  )
}

const deleteDatasetConfirm = async (row) => {
  await ElMessageBox.confirm(`确定删除数据集 "${row.name}"？`, '确认', { type: 'warning' })
  await evalAPI.deleteDataset(row.id)
  ElMessage.success('已删除')
  await loadDatasets()
}

const createDataset = async () => {
  if (!datasetForm.value.name || !datasetForm.value.kb_id) {
    ElMessage.warning('请填写名称并选择 KB')
    return
  }
  creating.value = true
  try {
    await evalAPI.createDataset(datasetForm.value)
    ElMessage.success('数据集已生成')
    showCreateDataset.value = false
    await loadDatasets()
    datasetForm.value = { name: '', description: '', n_questions: 20, kb_id: null }
  } finally {
    creating.value = false
  }
}

const resetForm = () => {
  form.value = {
    name: '',
    dataset_id: null,
    qa_sample_size: null,
    concurrency: 4,
    retrieval_strategies: ['vector'],
    rerank_models: ['BAAI/bge-reranker-base'],
    generation_models: ['mimo-v2.5-pro'],
    enabled_metrics: [...ALL_METRIC_KEYS],
    llm_metric_model: 'mimo-v2.5',
  }
}
</script>

<style scoped>
.eval-view {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}
.header-card {
  margin-bottom: 20px;
}
.subtitle {
  color: #999;
  margin-top: 8px;
}
</style>
