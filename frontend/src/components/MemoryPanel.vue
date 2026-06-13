<template>
  <div class="memory-panel" :class="{ open: visible }">
    <div class="panel-header">
      <h3>💾 Store 会话状态</h3>
      <el-button text @click="$emit('close')">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>

    <div class="panel-content">
      <div v-if="storeLoading" class="loading">加载中...</div>
      <div v-else-if="storeEntries.length === 0" class="empty">
        <p>暂无会话状态</p>
        <p class="hint">在对话中可以保存偏好、进度等信息</p>
      </div>
      <div v-else>
        <div v-for="entry in storeEntries" :key="entry.key" class="store-item">
          <div class="store-key">{{ entry.key }}</div>
          <div class="store-value">{{ formatValue(entry.value) }}</div>
          <el-button text size="small" type="danger" @click="deleteStore(entry.key)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </div>
      <el-button size="small" @click="clearStore" type="danger" plain style="margin-top: 12px">
        清空所有状态
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { storeAPI } from '../api'
import { Close, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['close'])

const storeEntries = ref([])
const storeLoading = ref(false)

watch(() => props.visible, (val) => {
  if (val) loadStore()
})

async function loadStore() {
  storeLoading.value = true
  try {
    const { data } = await storeAPI.list()
    storeEntries.value = data || []
  } catch { storeEntries.value = [] }
  storeLoading.value = false
}

async function deleteStore(key) {
  try {
    await storeAPI.delete(key)
    ElMessage.success('已删除')
    loadStore()
  } catch { /* noop */ }
}

async function clearStore() {
  try {
    await ElMessageBox.confirm('确定清空所有会话状态？', '确认', { type: 'warning' })
    await storeAPI.clear()
    ElMessage.success('已清空')
    loadStore()
  } catch { /* noop */ }
}

function formatValue(v) {
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
</script>

<style scoped>
.memory-panel {
  position: fixed;
  right: -400px;
  top: 0;
  width: 400px;
  height: 100vh;
  background: #fff;
  box-shadow: -4px 0 12px rgba(0,0,0,0.1);
  z-index: 1000;
  transition: right 0.3s;
  display: flex;
  flex-direction: column;
}

.memory-panel.open {
  right: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #e4e7ed;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
}

.panel-content {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
}

.store-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  margin-bottom: 8px;
}

.store-key {
  font-weight: 600;
  font-size: 13px;
  color: #409eff;
}

.store-value {
  flex: 1;
  font-size: 13px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.loading, .empty {
  text-align: center;
  color: #909399;
  padding: 40px 0;
}

.hint {
  font-size: 12px;
  margin-top: 8px;
}
</style>
