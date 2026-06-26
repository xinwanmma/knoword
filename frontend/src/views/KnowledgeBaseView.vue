<template>
  <div class="kb-page">
    <div class="page-header">
      <h2>知识库管理</h2>
      <el-button type="primary" @click="showCreateDialog">
        <el-icon><Plus /></el-icon> 创建知识库
      </el-button>
    </div>

    <!-- 知识库列表 -->
    <div class="kb-grid">
      <el-card
        v-for="kb in knowledgeBases"
        :key="kb.id"
        class="kb-card"
        shadow="hover"
      >
        <template #header>
          <div class="kb-card-header">
            <div class="kb-title">
              <el-icon color="#909399"><Folder /></el-icon>
              <span>{{ kb.name }}</span>
            </div>
            <div class="kb-actions">
              <el-button text size="small" @click="openDocDialog(kb)">
                <el-icon><Document /></el-icon>
              </el-button>
              <el-button text size="small" @click="editKb(kb)">
                <el-icon><Edit /></el-icon>
              </el-button>
              <el-button text size="small" type="danger" @click="deleteKb(kb)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </template>
        <div class="kb-meta">
          <span class="doc-count">{{ kb.document_count }} 个文档</span>
        </div>
        <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
        <div class="kb-tags">
          <el-tag size="small" type="info">{{ kb.embedding_model }}</el-tag>
          <el-tag size="small" type="success">{{ kb.chunking_strategy }}</el-tag>
          <el-tag size="small" type="warning">{{ kb.retrieval_strategy }}</el-tag>
          <el-tag v-if="kb.rerank_model" size="small" type="danger">rerank</el-tag>
        </div>
      </el-card>

      <div v-if="knowledgeBases.length === 0" class="empty-state">
        <el-empty description="暂无知识库">
          <el-button type="primary" @click="showCreateDialog">创建第一个知识库</el-button>
        </el-empty>
      </div>
    </div>

    <!-- 创建/编辑知识库对话框 -->
    <el-dialog
      v-model="kbDialogVisible"
      :title="editingKb ? '编辑知识库' : '创建知识库'"
      width="640px"
    >
      <el-form :model="kbForm" label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="kbForm.name" placeholder="知识库名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="kbForm.description" type="textarea" :rows="2" placeholder="可选描述" />
        </el-form-item>

        <el-divider content-position="left">Embedding 模型</el-divider>
        <el-form-item label="Embedding">
          <el-select v-model="kbForm.embedding_model" style="width: 100%" @change="onEmbeddingChange">
            <el-option-group label="Ollama（本地）">
              <el-option label="qwen3-embedding:0.6b（推荐）" value="qwen3-embedding:0.6b" />
            </el-option-group>
            <el-option-group label="HuggingFace（本地离线）">
              <el-option label="shibing624/text2vec-base-chinese" value="shibing624/text2vec-base-chinese" />
            </el-option-group>
            <el-option-group label="SiliconFlow（云端 API，需 Key）">
              <el-option label="Qwen/Qwen3-Embedding-4B" value="Qwen/Qwen3-Embedding-4B" />
              <el-option label="Qwen/Qwen3-Embedding-8B" value="Qwen/Qwen3-Embedding-8B" />
            </el-option-group>
          </el-select>
        </el-form-item>

        <el-divider content-position="left">分块策略</el-divider>
        <el-form-item label="策略">
          <el-radio-group v-model="kbForm.chunking_strategy">
            <el-radio-button label="fixed_size">固定长度</el-radio-button>
            <el-radio-button label="recursive">递归分割</el-radio-button>
            <el-radio-button label="semantic">语义切分</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="块大小">
          <el-input-number v-model="kbForm.chunk_size" :min="100" :max="2000" :step="50" />
          <span class="form-hint">字符数，100-2000</span>
        </el-form-item>
        <el-form-item label="重叠">
          <el-input-number v-model="kbForm.chunk_overlap" :min="0" :max="500" :step="10" />
          <span class="form-hint">块间重叠字符数</span>
        </el-form-item>

        <el-divider content-position="left">检索策略</el-divider>
        <el-form-item label="Retrieval">
          <el-radio-group v-model="kbForm.retrieval_strategy">
            <el-radio-button label="vector">向量检索</el-radio-button>
            <el-radio-button label="bm25">BM25</el-radio-button>
            <el-radio-button label="rerank">向量 + Rerank</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="kbForm.retrieval_strategy === 'rerank'" label="Rerank 模型">
          <el-select v-model="kbForm.rerank_model" style="width: 100%">
            <el-option-group label="HuggingFace（本地）">
              <el-option label="BAAI/bge-reranker-base" value="BAAI/bge-reranker-base" />
            </el-option-group>
            <el-option-group label="SiliconFlow（云端 API，需 Key）">
              <el-option label="Qwen/Qwen3-Reranker-4B" value="Qwen/Qwen3-Reranker-4B" />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item v-if="kbForm.retrieval_strategy === 'rerank'" label="Top N">
          <el-input-number v-model="kbForm.rerank_top_n" :min="5" :max="100" :step="5" />
          <span class="form-hint">重排序后保留的文档数</span>
        </el-form-item>

        <el-alert
          v-if="editingKb && embeddingChanged"
          type="warning"
          :closable="false"
          show-icon
          style="margin-top: 12px"
        >
          <template #title>修改 Embedding 模型需重新上传所有文档</template>
          现有向量是用 {{ editingKb.embedding_model }} 生成的，更换后需删除文档后重新上传。
        </el-alert>
      </el-form>
      <template #footer>
        <el-button @click="kbDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveKb">
          {{ editingKb ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 文档管理对话框 -->
    <el-dialog
      v-model="docDialogVisible"
      :title="`文档管理 - ${currentKb?.name}`"
      width="700px"
    >
      <!-- 上传区 -->
      <el-upload
        class="upload-area"
        drag
        multiple
        :auto-upload="false"
        :file-list="uploadFiles"
        :on-change="handleFileChange"
        :before-upload="() => false"
        accept=".pdf,.docx,.txt,.md,.xlsx,.pptx,.csv,.json,.html"
      >
        <el-icon size="40" color="#c0c4cc"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽文件到这里，或 <em>点击上传</em></div>
        <template #tip>
          <div class="el-upload__tip">
            支持 PDF、DOCX、TXT、MD、XLSX、PPTX、CSV、JSON、HTML，单文件最大 50MB
          </div>
        </template>
      </el-upload>
      <el-button
        type="primary"
        :loading="uploading"
        :disabled="uploadFiles.length === 0"
        style="margin-top: 12px"
        @click="handleUpload"
      >
        上传 {{ uploadFiles.length }} 个文件
      </el-button>

      <!-- 文档列表 -->
      <el-table :data="documents" style="margin-top: 16px" max-height="400">
        <el-table-column prop="filename" label="文件名" min-width="200" />
        <el-table-column prop="file_type" label="类型" width="80" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'ready'" type="success" size="small">就绪</el-tag>
            <el-tag v-else-if="row.status === 'processing'" type="warning" size="small">处理中</el-tag>
            <el-tag v-else type="danger" size="small">失败</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="分块数" width="80" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button text size="small" @click="reindexDoc(row)">
              <el-icon><Refresh /></el-icon>
            </el-button>
            <el-button text size="small" type="danger" @click="deleteDoc(row)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, computed } from 'vue'
import { kbAPI, docAPI } from '../api'
import { Plus, Edit, Delete, Document, Folder, UploadFilled, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const knowledgeBases = ref([])
const kbDialogVisible = ref(false)
const docDialogVisible = ref(false)
const editingKb = ref(null)
const saving = ref(false)
const currentKb = ref(null)
const documents = ref([])
const uploadFiles = ref([])
const uploading = ref(false)

// 表单默认值（与后端 KnowledgeBaseCreate schema 一致）
const DEFAULT_FORM = {
  name: '',
  description: '',
  embedding_model: 'qwen3-embedding:0.6b',
  chunking_strategy: 'recursive',
  chunk_size: 500,
  chunk_overlap: 50,
  retrieval_strategy: 'vector',
  rerank_model: 'BAAI/bge-reranker-base',
  rerank_top_n: 20,
}

const kbForm = reactive({ ...DEFAULT_FORM })

// 检测 embedding 模型变化（编辑时）
const embeddingChanged = computed(() => {
  if (!editingKb.value) return false
  return editingKb.value.embedding_model !== kbForm.embedding_model
})

onMounted(() => {
  loadKbs()
})

async function loadKbs() {
  try {
    const { data } = await kbAPI.list()
    knowledgeBases.value = data
  } catch (err) { console.error(err) }
}

function showCreateDialog() {
  editingKb.value = null
  Object.assign(kbForm, DEFAULT_FORM)
  kbDialogVisible.value = true
}

function editKb(kb) {
  editingKb.value = kb
  Object.assign(kbForm, {
    name: kb.name,
    description: kb.description || '',
    embedding_model: kb.embedding_model || DEFAULT_FORM.embedding_model,
    chunking_strategy: kb.chunking_strategy || DEFAULT_FORM.chunking_strategy,
    chunk_size: kb.chunk_size || DEFAULT_FORM.chunk_size,
    chunk_overlap: kb.chunk_overlap || DEFAULT_FORM.chunk_overlap,
    retrieval_strategy: kb.retrieval_strategy || DEFAULT_FORM.retrieval_strategy,
    rerank_model: kb.rerank_model || DEFAULT_FORM.rerank_model,
    rerank_top_n: kb.rerank_top_n || DEFAULT_FORM.rerank_top_n,
  })
  kbDialogVisible.value = true
}

async function saveKb() {
  if (!kbForm.name.trim()) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  if (kbForm.chunk_overlap >= kbForm.chunk_size) {
    ElMessage.warning('重叠字符数不能 ≥ 块大小')
    return
  }
  saving.value = true
  try {
    const payload = { ...kbForm }
    if (editingKb.value) {
      await kbAPI.update(editingKb.value.id, payload)
      ElMessage.success('更新成功')
    } else {
      await kbAPI.create(payload)
      ElMessage.success('创建成功')
    }
    kbDialogVisible.value = false
    await loadKbs()
  } catch (err) { console.error(err) }
  saving.value = false
}

function onEmbeddingChange() {
  // 占位：未来可以根据 embedding 切换推荐其他配置
}

async function deleteKb(kb) {
  try {
    await ElMessageBox.confirm(`确定删除知识库「${kb.name}」？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await kbAPI.delete(kb.id)
    ElMessage.success('已删除')
    await loadKbs()
  } catch (err) { console.error(err) }
}

async function openDocDialog(kb) {
  currentKb.value = kb
  uploadFiles.value = []
  docDialogVisible.value = true
  await loadDocuments(kb.id)
}

async function loadDocuments(kbId) {
  try {
    const { data } = await docAPI.listByKb(kbId)
    documents.value = data
  } catch (err) { console.error(err) }
}

function handleFileChange(file) {
  uploadFiles.value.push(file.raw)
}

async function handleUpload() {
  if (uploadFiles.value.length === 0) return
  uploading.value = true
  try {
    await docAPI.upload(currentKb.value.id, uploadFiles.value)
    ElMessage.success('上传成功，文档正在后台处理')
    uploadFiles.value = []
    await loadDocuments(currentKb.value.id)
    await loadKbs()
  } catch (err) { console.error(err) }
  uploading.value = false
}

async function deleteDoc(doc) {
  try {
    await ElMessageBox.confirm(`确定删除文档「${doc.filename}」？`, '确认', {
      type: 'warning',
    })
    await docAPI.delete(doc.id)
    ElMessage.success('已删除')
    await loadDocuments(currentKb.value.id)
    await loadKbs()
  } catch (err) { console.error(err) }
}

async function reindexDoc(doc) {
  try {
    await docAPI.reindex(doc.id)
    ElMessage.success('已开始重新索引')
    await loadDocuments(currentKb.value.id)
  } catch (err) { console.error(err) }
}
</script>

<style scoped>
.kb-page {
  padding: 20px;
  height: 100vh;
  overflow-y: auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.page-header h2 {
  color: #303133;
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.kb-card {
  border-radius: 12px;
}

.kb-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.kb-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 15px;
}

.kb-actions {
  display: flex;
  gap: 2px;
}

.kb-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.doc-count {
  color: #909399;
  font-size: 13px;
}

.kb-desc {
  color: #606266;
  font-size: 14px;
  line-height: 1.5;
  margin: 0 0 8px;
}

.kb-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}

.form-hint {
  margin-left: 12px;
  color: #909399;
  font-size: 12px;
}

.upload-area {
  width: 100%;
}

.empty-state {
  grid-column: 1 / -1;
  padding: 60px 0;
}
</style>
