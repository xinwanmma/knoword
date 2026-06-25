<template>
  <div class="admin-page">
    <h2 class="page-title">管理后台</h2>

    <el-tabs v-model="activeTab" class="admin-tabs">
      <!-- 统计 Tab -->
      <el-tab-pane label="系统统计" name="stats">
        <div v-if="stats" class="stats-grid">
          <el-card class="stat-card" shadow="hover">
            <div class="stat-icon" style="background: #ecf5ff; color: #409eff;">
              <el-icon size="28"><User /></el-icon>
            </div>
            <div class="stat-body">
              <div class="stat-value">{{ stats.users.total }}</div>
              <div class="stat-label">用户总数</div>
              <div class="stat-meta">
                管理员 {{ stats.users.admins }} · 普通 {{ stats.users.regular }}
              </div>
            </div>
          </el-card>

          <el-card class="stat-card" shadow="hover">
            <div class="stat-icon" style="background: #f0f9eb; color: #67c23a;">
              <el-icon size="28"><Folder /></el-icon>
            </div>
            <div class="stat-body">
              <div class="stat-value">{{ stats.knowledge_bases }}</div>
              <div class="stat-label">知识库总数</div>
            </div>
          </el-card>

          <el-card class="stat-card" shadow="hover">
            <div class="stat-icon" style="background: #fdf6ec; color: #e6a23c;">
              <el-icon size="28"><Document /></el-icon>
            </div>
            <div class="stat-body">
              <div class="stat-value">{{ stats.documents.total }}</div>
              <div class="stat-label">文档总数</div>
              <div class="stat-meta">
                就绪 {{ stats.documents.ready }} · 处理中 {{ stats.documents.processing }}
              </div>
            </div>
          </el-card>

          <el-card class="stat-card" shadow="hover">
            <div class="stat-icon" style="background: #fef0f0; color: #f56c6c;">
              <el-icon size="28"><ChatLineRound /></el-icon>
            </div>
            <div class="stat-body">
              <div class="stat-value">{{ stats.conversations }}</div>
              <div class="stat-label">对话总数</div>
              <div class="stat-meta">消息 {{ stats.messages }} 条</div>
            </div>
          </el-card>
        </div>

        <el-skeleton v-else :rows="4" animated />
      </el-tab-pane>

      <!-- 用户管理 Tab -->
      <el-tab-pane label="用户管理" name="users">
        <el-table :data="users" v-loading="loadingUsers" stripe>
          <el-table-column prop="username" label="用户名" min-width="120" />
          <el-table-column prop="email" label="邮箱" min-width="200" />
          <el-table-column label="角色" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.is_admin" type="danger" size="small">管理员</el-tag>
              <el-tag v-else type="info" size="small">普通用户</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="注册时间" width="180">
            <template #default="{ row }">
              {{ formatDate(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="!isSelf(row)"
                size="small"
                :type="row.is_admin ? 'warning' : 'primary'"
                @click="toggleAdminRole(row)"
              >
                {{ row.is_admin ? '取消管理员' : '设为管理员' }}
              </el-button>
              <el-tag v-else size="small" type="info">当前用户</el-tag>
              <el-button
                v-if="!isSelf(row)"
                size="small"
                type="danger"
                @click="deleteUser(row)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 知识库管理 Tab -->
      <el-tab-pane label="全局知识库" name="kbs">
        <el-table :data="kbs" v-loading="loadingKbs" stripe>
          <el-table-column prop="name" label="知识库名" min-width="160" />
          <el-table-column label="所有者" width="140">
            <template #default="{ row }">
              {{ row.owner_username }}
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
          <el-table-column prop="document_count" label="文档数" width="100" />
          <el-table-column label="创建时间" width="180">
            <template #default="{ row }">
              {{ formatDate(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="viewKbDocs(row)">查看文档</el-button>
              <el-button size="small" type="danger" @click="adminDeleteKb(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 查看文档对话框 -->
    <el-dialog
      v-model="docsDialogVisible"
      :title="`${currentKb?.name} 的文档`"
      width="700px"
    >
      <el-table :data="kbDocs" v-loading="loadingDocs" max-height="500">
        <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip />
        <el-table-column prop="file_type" label="类型" width="80" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'ready'" type="success" size="small">就绪</el-tag>
            <el-tag v-else-if="row.status === 'processing'" type="warning" size="small">处理中</el-tag>
            <el-tag v-else type="danger" size="small">失败</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="分块" width="80" />
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onActivated } from 'vue'
import { adminAPI } from '../api'
import { useUserStore } from '../stores/user'
import { User, Folder, Document, ChatLineRound } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const userStore = useUserStore()

const activeTab = ref('stats')
const stats = ref(null)
const users = ref([])
const kbs = ref([])
const kbDocs = ref([])
const currentKb = ref(null)
const docsDialogVisible = ref(false)
const loadingUsers = ref(false)
const loadingKbs = ref(false)
const loadingDocs = ref(false)

onMounted(() => {
  loadStats()
  loadUsers()
  loadAllKbs()
})

onActivated(() => {
  loadStats()
  loadUsers()
  loadAllKbs()
})

async function loadStats() {
  try {
    const { data } = await adminAPI.getStats()
    stats.value = data
  } catch (err) { console.error(err) }
}

async function loadUsers() {
  loadingUsers.value = true
  try {
    const { data } = await adminAPI.listUsers()
    users.value = data
  } catch (err) { console.error(err) }
  loadingUsers.value = false
}

async function loadAllKbs() {
  loadingKbs.value = true
  try {
    const { data } = await adminAPI.listAllKbs()
    kbs.value = data
  } catch (err) { console.error(err) }
  loadingKbs.value = false
}

function isSelf(user) {
  return user.id === userStore.user?.id
}

async function toggleAdminRole(user) {
  try {
    await ElMessageBox.confirm(
      `确认将 ${user.username} 设为${user.is_admin ? '普通用户' : '管理员'}？`,
      '确认',
      { type: 'warning' }
    )
    await adminAPI.toggleAdmin(user.id)
    ElMessage.success('已更新')
    await loadUsers()
    await loadStats()
  } catch (err) {
    if (err !== 'cancel' && err !== 'close') console.error(err)
  }
}

async function deleteUser(user) {
  try {
    await ElMessageBox.confirm(
      `确定删除用户「${user.username}」？该用户的所有知识库、文档、对话将被一并删除，且不可恢复！`,
      '危险操作',
      {
        type: 'error',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      }
    )
    await adminAPI.deleteUser(user.id)
    ElMessage.success('已删除')
    await loadUsers()
    await loadStats()
  } catch (err) {
    if (err !== 'cancel' && err !== 'close') console.error(err)
  }
}

async function viewKbDocs(kb) {
  currentKb.value = kb
  docsDialogVisible.value = true
  loadingDocs.value = true
  try {
    const { data } = await adminAPI.listKbDocs(kb.id)
    kbDocs.value = data
  } catch (err) { console.error(err) }
  loadingDocs.value = false
}

async function adminDeleteKb(kb) {
  try {
    await ElMessageBox.confirm(
      `确定删除知识库「${kb.name}」（所有者: ${kb.owner_username}）？\n所有文档和向量数据将被清除。`,
      '危险操作',
      {
        type: 'error',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      }
    )
    await adminAPI.deleteKb(kb.id)
    ElMessage.success('已删除')
    await loadAllKbs()
    await loadStats()
  } catch (err) {
    if (err !== 'cancel' && err !== 'close') console.error(err)
  }
}

function formatDate(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.admin-page {
  padding: 20px 24px;
  height: 100vh;
  overflow-y: auto;
  background: #f5f7fa;
}

.page-title {
  margin: 0 0 16px;
  color: #303133;
  font-size: 20px;
}

.admin-tabs {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  border-radius: 12px;
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-body {
  flex: 1;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: #606266;
  margin-top: 2px;
}

.stat-meta {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
