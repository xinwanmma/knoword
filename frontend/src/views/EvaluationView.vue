<template>
  <div class="eval-view">
    <el-card class="header-card">
      <h2>评估中心</h2>
      <p class="subtitle">对比不同 Embedding / Retrieval / Rerank / Generation 模型效果</p>
    </el-card>

    <el-tabs v-model="activeTab" type="border-card">
      <!-- ====== 新建评估 ====== -->
      <el-tab-pane label="新建评估" name="create">
        <el-form :model="form" label-width="140px" style="max-width: 800px">
          <el-form-item label="评估名称">
            <el-input v-model="form.name" placeholder="例如：test01" />
          </el-form-item>

          <el-form-item label="知识库">
            <el-select v-model="form.kb_id" placeholder="选择 KB" @change="onKbChange" style="width: 100%">
              <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
            </el-select>
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

          <el-form-item label="QA 数量">
            <el-input-number v-model="form.qa_count" :min="1" :max="200" />
            <span style="margin-left: 10px; color: #999">默认 20</span>
          </el-form-item>

          <el-form-item label="并行度">
            <el-slider v-model="form.concurrency" :min="1" :max="8" show-stops :marks="concurrencyMarks" />
          </el-form-item>

          <el-form-item label="Embedding 模型">
            <el-checkbox-group v-model="form.embedding_models">
              <el-checkbox v-for="m in models.embeddings || []" :key="m.id" :label="m.id">
                {{ m.id }} <el-tag size="small" :type="m.type === 'local' ? 'success' : 'warning'">{{ m.type }}</el-tag>
              </el-checkbox>
            </el-checkbox-group>
          </el-form-item>

          <el-form-item label="Retrieval 策略">
            <el-checkbox-group v-model="form.retrieval_strategies" @change="onRetrievalChange">
              <el-checkbox v-for="s in retrievalOptions" :key="s" :label="s">{{ s }}</el-checkbox>
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

          <el-form-item label="LLM-as-Judge">
            <el-tag type="info">mimo-2.5（固定）</el-tag>
            <span style="margin-left: 10px; color: #999">不可修改</span>
          </el-form-item>

          <el-form-item label="RAGAS 评估">
            <el-switch v-model="form.use_ragas" />
            <span style="margin-left: 10px; color: #999">
              run 完成后批量评估（更全面但更慢，可能需要 5-10 分钟）
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
        <p>配置：</p>
        <ul>
          <li>Embedding: {{ reportData.config.embedding_models?.join(', ') }}</li>
          <li>Retrieval: {{ reportData.config.retrieval_strategies?.join(', ') }}</li>
          <li v-if="reportData.config.rerank_models?.length">Rerank: {{ reportData.config.rerank_models.join(', ') }}</li>
          <li>Generation: {{ reportData.config.generation_models?.join(', ') }}</li>
          <li>LLM-as-Judge: mimo-2.5（固定）</li>
          <li>RAGAS: {{ reportData.config.use_ragas ? '✅ 启用' : '❌ 未启用' }}</li>
        </ul>
        <h4>Summary</h4>
        <pre style="background: #f5f5f5; padding: 12px; border-radius: 4px; max-height: 400px; overflow: auto;">{{ JSON.stringify(reportData.summary, null, 2) }}</pre>

        <!-- RAGAS 高亮 -->
        <div v-if="reportData.summary?.ragas && typeof reportData.summary.ragas === 'object'">
          <h4>RAGAS 总体均值</h4>
          <el-table :data="ragasTableData" border size="small">
            <el-table-column prop="name" label="指标" />
            <el-table-column prop="value" label="分数" />
          </el-table>
        </div>

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
            <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
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
const form = ref({
  name: '',
  kb_id: null,
  dataset_id: null,
  qa_count: 20,
  concurrency: 4,
  embedding_models: ['qwen3-embedding:0.6b'],
  retrieval_strategies: ['vector'],
  rerank_models: ['BAAI/bge-reranker-base'],
  generation_models: ['mimo-v2.5-pro'],
  use_ragas: false,
})

const concurrencyMarks = { 1: '1', 2: '2', 4: '4', 6: '6', 8: '8' }
const retrievalOptions = ['vector', 'bm25', 'rerank', 'graph']

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
  return form.value.name && form.value.dataset_id && form.value.embedding_models.length
    && form.value.retrieval_strategies.length && form.value.generation_models.length
})

const statusType = (s) => ({
  pending: 'info', running: 'warning', stopped: '',
  completed: 'success', failed: 'danger',
}[s] || '')

// RAGAS 指标名 → 友好显示
const RAGAS_DISPLAY = {
  faithfulness: 'Faithfulness（忠实度）',
  answer_relevancy: 'Answer Relevancy（答案相关度）',
  context_relevancy: 'Context Relevancy（上下文相关度）',
  context_recall: 'Context Recall（上下文召回率）',
  context_precision: 'Context Precision（上下文精度）',
  answer_correctness: 'Answer Correctness（答案正确性）',
}

const ragasTableData = computed(() => {
  if (!reportData.value?.summary?.ragas) return []
  return Object.entries(reportData.value.summary.ragas)
    .filter(([k, v]) => k !== 'error' && typeof v === 'number')
    .map(([k, v]) => ({ name: RAGAS_DISPLAY[k] || k, value: v.toFixed(4) }))
})

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

const onKbChange = () => {}
const onRetrievalChange = () => {}

const startRun = async () => {
  starting.value = true
  try {
    await evalAPI.createRun({
      name: form.value.name,
      dataset_id: form.value.dataset_id,
      embedding_models: form.value.embedding_models,
      retrieval_strategies: form.value.retrieval_strategies,
      rerank_models: form.value.retrieval_strategies.includes('rerank') ? form.value.rerank_models : [],
      generation_models: form.value.generation_models,
      concurrency: form.value.concurrency,
      use_ragas: form.value.use_ragas,
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
    kb_id: null,
    dataset_id: null,
    qa_count: 20,
    concurrency: 4,
    embedding_models: ['qwen3-embedding:0.6b'],
    retrieval_strategies: ['vector'],
    rerank_models: ['BAAI/bge-reranker-base'],
    generation_models: ['mimo-v2.5-pro'],
    use_ragas: false,
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
