<template>
  <div class="kb-page">
    <div class="page-header">
      <h2>知识库管理</h2>
      <div class="header-actions">
        <el-select v-model="filterCategory" placeholder="按分类筛选" clearable size="default" style="width: 150px">
          <el-option v-for="cat in categories" :key="cat.id" :label="cat.name" :value="cat.id" />
        </el-select>
        <el-button type="primary" @click="showCreateDialog">
          <el-icon><Plus /></el-icon> 创建知识库
        </el-button>
      </div>
    </div>

    <!-- 知识库列表 -->
    <div class="kb-grid">
      <el-card
        v-for="kb in filteredKbs"
        :key="kb.id"
        class="kb-card"
        shadow="hover"
      >
        <template #header>
          <div class="kb-card-header">
            <div class="kb-title">
              <el-icon v-if="kb.is_global" color="#e6a23c"><Star /></el-icon>
              <el-icon v-else color="#909399"><Folder /></el-icon>
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
          <el-tag v-if="kb.category_name" size="small" type="info">{{ kb.category_name }}</el-tag>
          <el-tag v-if="kb.is_global" size="small" type="warning">全局</el-tag>
          <el-tag v-else size="small">个人</el-tag>
          <span class="doc-count">{{ kb.document_count }} 个文档</span>
        </div>
        <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
      </el-card>

      <div v-if="filteredKbs.length === 0" class="empty-state">
        <el-empty description="暂无知识库">
          <el-button type="primary" @click="showCreateDialog">创建第一个知识库</el-button>
        </el-empty>
      </div>
    </div>

    <!-- 创建/编辑知识库对话框 -->
    <el-dialog
      v-model="kbDialogVisible"
      :title="editingKb ? '编辑知识库' : '创建知识库'"
      width="500px"
    >
      <el-form :model="kbForm" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="kbForm.name" placeholder="知识库名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="kbForm.description" type="textarea" :rows="3" placeholder="可选描述" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="kbForm.category_id" placeholder="选择分类" clearable style="width: 100%">
            <el-option v-for="cat in categories" :key="cat.id" :label="cat.name" :value="cat.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!editingKb" label="可见性">
          <el-radio-group v-model="kbForm.is_global">
            <el-radio :value="false">个人</el-radio>
            <el-radio :value="true" :disabled="!userStore.isAdmin">全局（仅管理员）</el-radio>
          </el-radio-group>
        </el-form-item>
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
import { ref, computed, onMounted, reactive } from 'vue'
import { kbAPI, docAPI, categoryAPI } from '../api'
import { useUserStore } from '../stores/user'
import { Plus, Edit, Delete, Document, Folder, Star, UploadFilled, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const userStore = useUserStore()

const knowledgeBases = ref([])
const categories = ref([])
const filterCategory = ref(null)
const kbDialogVisible = ref(false)
const docDialogVisible = ref(false)
const editingKb = ref(null)
const saving = ref(false)
const currentKb = ref(null)
const documents = ref([])
const uploadFiles = ref([])
const uploading = ref(false)

const kbForm = reactive({
  name: '',
  description: '',
  category_id: null,
  is_global: false,
})

const filteredKbs = computed(() => {
  if (!filterCategory.value) return knowledgeBases.value
  return knowledgeBases.value.filter((kb) => kb.category_id === filterCategory.value)
})

onMounted(() => {
  loadKbs()
  loadCategories()
})

async function loadKbs() {
  try {
    const { data } = await kbAPI.list()
    knowledgeBases.value = data
  } catch { /* noop */ }
}

async function loadCategories() {
  try {
    const { data } = await categoryAPI.list()
    categories.value = data
  } catch { /* noop */ }
}

function showCreateDialog() {
  editingKb.value = null
  kbForm.name = ''
  kbForm.description = ''
  kbForm.category_id = null
  kbForm.is_global = false
  kbDialogVisible.value = true
}

function editKb(kb) {
  editingKb.value = kb
  kbForm.name = kb.name
  kbForm.description = kb.description || ''
  kbForm.category_id = kb.category_id
  kbForm.is_global = kb.is_global
  kbDialogVisible.value = true
}

async function saveKb() {
  if (!kbForm.name.trim()) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  saving.value = true
  try {
    if (editingKb.value) {
      await kbAPI.update(editingKb.value.id, {
        name: kbForm.name,
        description: kbForm.description,
        category_id: kbForm.category_id,
      })
      ElMessage.success('更新成功')
    } else {
      await kbAPI.create({
        name: kbForm.name,
        description: kbForm.description,
        category_id: kbForm.category_id,
        is_global: kbForm.is_global,
      })
      ElMessage.success('创建成功')
    }
    kbDialogVisible.value = false
    await loadKbs()
  } catch { /* noop */ }
  saving.value = false
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
  } catch { /* noop */ }
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
  } catch { /* noop */ }
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
  } catch { /* noop */ }
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
  } catch { /* noop */ }
}

async function reindexDoc(doc) {
  try {
    await docAPI.reindex(doc.id)
    ElMessage.success('已开始重新索引')
    await loadDocuments(currentKb.value.id)
  } catch { /* noop */ }
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

.header-actions {
  display: flex;
  gap: 12px;
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
}

.upload-area {
  width: 100%;
}

.empty-state {
  grid-column: 1 / -1;
  padding: 60px 0;
}
</style>
