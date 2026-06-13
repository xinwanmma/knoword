<template>
  <div class="admin-page">
    <h2>管理员面板</h2>

    <el-tabs v-model="activeTab">
      <!-- 用户管理 -->
      <el-tab-pane label="用户管理" name="users">
        <div class="section-header">
          <h3>用户列表</h3>
          <el-button type="primary" size="small" @click="showCategoryDialog">
            <el-icon><Plus /></el-icon> 添加分类
          </el-button>
        </div>
        <el-table :data="users" style="width: 100%">
          <el-table-column prop="username" label="用户名" width="150" />
          <el-table-column prop="email" label="邮箱" min-width="200" />
          <el-table-column label="角色" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.is_admin" type="warning" size="small">管理员</el-tag>
              <el-tag v-else size="small">用户</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="注册时间" width="180">
            <template #default="{ row }">
              {{ formatDate(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button
                size="small"
                :type="row.is_admin ? 'info' : 'warning'"
                text
                @click="toggleAdmin(row)"
              >
                {{ row.is_admin ? '取消管理员' : '设为管理员' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 分类管理 -->
      <el-tab-pane label="分类管理" name="categories">
        <div class="section-header">
          <h3>知识库分类</h3>
          <el-button type="primary" size="small" @click="showCategoryDialog">
            <el-icon><Plus /></el-icon> 添加分类
          </el-button>
        </div>
        <el-table :data="categories" style="width: 100%">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="name" label="分类名称" min-width="200" />
        </el-table>

        <el-dialog v-model="catDialogVisible" title="添加分类" width="400px">
          <el-input v-model="newCatName" placeholder="分类名称" @keyup.enter="createCategory" />
          <template #footer>
            <el-button @click="catDialogVisible = false">取消</el-button>
            <el-button type="primary" @click="createCategory">创建</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <!-- 系统统计 -->
      <el-tab-pane label="系统统计" name="stats">
        <el-row :gutter="20">
          <el-col :span="8">
            <el-statistic title="知识库数量" :value="stats.kbCount" />
          </el-col>
          <el-col :span="8">
            <el-statistic title="文档数量" :value="stats.docCount" />
          </el-col>
          <el-col :span="8">
            <el-statistic title="用户数量" :value="stats.userCount" />
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { kbAPI, categoryAPI, adminAPI } from '../api'
import api from '../api'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const activeTab = ref('users')
const users = ref([])
const categories = ref([])
const catDialogVisible = ref(false)
const newCatName = ref('')
const stats = reactive({ kbCount: 0, docCount: 0, userCount: 0 })

onMounted(() => {
  loadTabData(activeTab.value)
})

watch(activeTab, (tab) => {
  loadTabData(tab)
})

async function loadTabData(tab) {
  try {
    if (tab === 'users' && users.value.length === 0) {
      const { data } = await adminAPI.listUsers()
      users.value = data
      stats.userCount = data.length
    } else if (tab === 'categories' && categories.value.length === 0) {
      const { data } = await categoryAPI.list()
      categories.value = data
    } else if (tab === 'stats') {
      const { data: kbRes } = await kbAPI.list()
      stats.kbCount = kbRes.length
      stats.docCount = kbRes.reduce((sum, kb) => sum + (kb.document_count || 0), 0)
    }
  } catch (err) { console.error(err) }
}

async function toggleAdmin(user) {
  const action = user.is_admin ? '取消管理员' : '设为管理员'
  try {
    await ElMessageBox.confirm(
      `确定将 ${user.username} ${action}？`,
      '确认操作',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
    const { data } = await adminAPI.toggleAdmin(user.id)
    ElMessage.success(data.message)
    await loadTabData('users')
  } catch (err) { console.error(err) }
}

function showCategoryDialog() {
  newCatName.value = ''
  catDialogVisible.value = true
}

async function createCategory() {
  if (!newCatName.value.trim()) {
    ElMessage.warning('请输入分类名称')
    return
  }
  try {
    await categoryAPI.create({ name: newCatName.value })
    ElMessage.success('创建成功')
    catDialogVisible.value = false
    const { data } = await categoryAPI.list()
    categories.value = data
  } catch (err) { console.error(err) }
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}
</script>

<style scoped>
.admin-page {
  padding: 20px;
  height: 100vh;
  overflow-y: auto;
}

.admin-page h2 {
  color: #303133;
  margin-bottom: 20px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.section-header h3 {
  color: #606266;
  font-size: 16px;
}
</style>
