<template>
  <div class="chat-layout">
    <!-- 左侧：历史对话列表 -->
    <div class="chat-sidebar">
      <div class="sidebar-header">
        <h3>对话历史</h3>
        <el-button type="primary" size="small" @click="newChat">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
      </div>
      <div class="conversation-list">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="conversation-item"
          :class="{ active: currentConvId === conv.id }"
          @click="loadConversation(conv.id)"
        >
          <el-icon><ChatLineRound /></el-icon>
          <span class="conv-title">{{ conv.title }}</span>
          <el-icon class="delete-btn" @click.stop="deleteConversation(conv.id)"><Delete /></el-icon>
        </div>
        <div v-if="conversations.length === 0" class="empty-tip">
          暂无对话记录
        </div>
      </div>
    </div>

    <!-- 右侧：对话区 -->
    <div class="chat-main">
      <!-- 知识库选择栏 -->
      <div class="kb-selector">
        <div class="selector-options">
          <el-radio-group v-model="searchMode" size="small">
            <el-radio-button value="selected">指定知识库</el-radio-button>
            <el-radio-button value="all">搜索全部</el-radio-button>
          </el-radio-group>
        </div>
        <div v-if="searchMode === 'selected'" class="kb-tags">
          <el-checkbox-group v-model="selectedKbIds" :max="10">
            <el-checkbox
              v-for="kb in knowledgeBases"
              :key="kb.id"
              :value="kb.id"
              border
              size="small"
            >
              {{ kb.name }}
            </el-checkbox>
          </el-checkbox-group>
        </div>
      </div>

      <!-- 消息列表 -->
      <div ref="messagesContainer" class="messages-area">
        <div v-if="messages.length === 0" class="empty-chat">
          <el-icon size="60" color="#c0c4cc"><ChatDotRound /></el-icon>
          <p>开始提问吧</p>
        </div>

        <div v-for="(msg, idx) in parsedMessages" :key="idx">
          <!-- 用户消息 -->
          <div v-if="msg.role === 'user'" class="message-bubble message-user">
            {{ msg.content }}
          </div>

          <!-- AI 回答 -->
          <div v-else class="assistant-block">
            <!-- 引用来源 -->
            <div v-if="msg.sources && msg.sources.length > 0" class="sources-section">
              <div class="sources-title">
                <el-icon><Document /></el-icon> 引用来源 ({{ msg.sources.length }})
              </div>
              <div
                v-for="(src, si) in msg.sources"
                :key="si"
                class="source-card"
                @click="toggleSource(idx, si)"
              >
                <div class="source-header">
                  <el-icon><Document /></el-icon>
                  <span>{{ src.filename }}</span>
                  <span v-if="src.page">第{{ src.page }}页</span>
                  <el-tag size="small" type="info">相关度 {{ (src.score * 100).toFixed(0) }}%</el-tag>
                </div>
                <div
                  v-if="expandedSources[`${idx}-${si}`]"
                  class="source-full"
                >
                  {{ src.content }}
                </div>
                <div v-else class="source-content">{{ src.content }}</div>
              </div>
            </div>

            <!-- 回答内容 -->
            <div class="message-bubble message-assistant markdown-body" v-html="msg.html" />
          </div>
        </div>

        <!-- 正在生成的流式回答 -->
        <div v-if="streaming" class="assistant-block">
          <div v-if="!streamText && streamStatus" class="status-indicator">
            <span class="status-dot"></span>
            {{ streamStatus }}
          </div>
          <div v-if="streamSources.length > 0" class="sources-section">
            <div class="sources-title">
              <el-icon><Document /></el-icon> 引用来源 ({{ streamSources.length }})
            </div>
            <div v-for="(src, si) in streamSources" :key="si" class="source-card">
              <div class="source-header">
                <el-icon><Document /></el-icon>
                <span>{{ src.filename }}</span>
                <span v-if="src.page">第{{ src.page }}页</span>
              </div>
              <div class="source-content">{{ src.content }}</div>
            </div>
          </div>
          <div class="message-bubble message-assistant markdown-body" v-html="renderMarkdown(streamText)" />
          <span class="typing-cursor" />
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <el-input
          v-model="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="输入你的问题..."
          :disabled="streaming"
          @keydown.enter.exact.prevent="sendMessage"
        />
        <el-button
          type="primary"
          :icon="Promotion"
          :disabled="streaming || !inputText.trim()"
          circle
          size="large"
          @click="sendMessage"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
import { chatAPI, kbAPI } from '../api'
import { useUserStore } from '../stores/user'
import { Plus, ChatLineRound, Delete, Document, Promotion } from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { ElMessage } from 'element-plus'

const userStore = useUserStore()

// 状态
const messages = ref([])
const conversations = ref([])
const currentConvId = ref(null)
const inputText = ref('')
const streaming = ref(false)
const streamText = ref('')
const streamSources = ref([])
const streamStatus = ref('')
const searchMode = ref('selected')
const selectedKbIds = ref([])
const knowledgeBases = ref([])
const expandedSources = reactive({})
const messagesContainer = ref()
let streamController = null

// 修复 Bug #7：切换模式时重置 KB 选择
watch(searchMode, (newMode) => {
  if (newMode === 'all') {
    selectedKbIds.value = []
  }
})

function resetStreamState() {
  streamText.value = ''
  streamSources.value = []
  streamStatus.value = ''
}

onUnmounted(() => {
  if (streamController) {
    streamController.abort()
  }
})

onMounted(async () => {
  await userStore.fetchUser().catch(() => {})
  if (userStore.isLoggedIn) {
    await Promise.all([loadConversations(), loadKnowledgeBases()])
  }
})

async function loadKnowledgeBases() {
  try {
    const { data } = await kbAPI.list()
    knowledgeBases.value = data
  } catch (err) { console.error(err) }
}

async function loadConversations() {
  try {
    const { data } = await chatAPI.history()
    conversations.value = data
  } catch (err) { console.error(err) }
}

async function loadConversation(convId) {
  currentConvId.value = convId
  resetStreamState()  // 修复 Bug #15：切换对话时清理流式状态
  try {
    const { data } = await chatAPI.getMessages(convId)
    messages.value = data
    const conv = conversations.value.find(c => c.id === convId)
    if (conv && conv.kb_ids && conv.kb_ids.length > 0) {
      selectedKbIds.value = conv.kb_ids
      searchMode.value = 'selected'
    }
    scrollToBottom()
  } catch (err) { console.error(err) }
}

function newChat() {
  currentConvId.value = null
  messages.value = []
  inputText.value = ''
  resetStreamState()
}

async function deleteConversation(convId) {
  try {
    await chatAPI.deleteConversation(convId)
    conversations.value = conversations.value.filter((c) => c.id !== convId)
    if (currentConvId.value === convId) {
      newChat()
    }
    ElMessage.success('已删除')
  } catch (err) { console.error(err) }
}

function sendMessage() {
  const query = inputText.value.trim()
  if (!query || streaming.value) return

  messages.value.push({ role: 'user', content: query })
  inputText.value = ''
  resetStreamState()  // 修复 Bug #6: 重置 status
  streamStatus.value = '正在思考...'
  streaming.value = true
  scrollToBottom()

  const reqData = {
    query,
    search_all: searchMode.value === 'all',
    kb_ids: selectedKbIds.value,
    conversation_id: currentConvId.value,
  }

  streamController = chatAPI.stream(reqData, {
    onToken: (token) => {
      streamText.value += token
      // 第一个 token 到达时清掉 status（进入流式输出阶段）
      if (streamStatus.value) streamStatus.value = ''
      scrollToBottom()
    },
    onSources: (sources) => {
      streamSources.value = sources
      // 修复 Bug #6: sources 到达后清掉 status
      streamStatus.value = ''
    },
    onStatus: (data) => {
      streamStatus.value = data.message
    },
    onDone: (data) => {
      streaming.value = false
      currentConvId.value = data.conversation_id
      messages.value.push({
        role: 'assistant',
        content: streamText.value,
        sources: streamSources.value.length > 0 ? [...streamSources.value] : null,
      })
      resetStreamState()
      loadConversations()
      scrollToBottom()
    },
    onError: (msg) => {
      streaming.value = false
      ElMessage.error(msg)
      resetStreamState()
    },
  })
}

function toggleSource(msgIdx, srcIdx) {
  const key = `${msgIdx}-${srcIdx}`
  expandedSources[key] = !expandedSources[key]
}

function renderMarkdown(text) {
  if (!text) return ''
  try {
    return DOMPurify.sanitize(marked.parse(text))
  } catch {
    return text
  }
}

const parsedMessages = computed(() => {
  return messages.value.map(msg => ({
    ...msg,
    html: msg.role === 'assistant' ? renderMarkdown(msg.content) : null
  }))
})

let scrollRAF = null
function scrollToBottom() {
  if (scrollRAF) return
  scrollRAF = requestAnimationFrame(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
    scrollRAF = null
  })
}
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
}

.chat-sidebar {
  width: 260px;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid #e4e7ed;
}

.sidebar-header h3 {
  font-size: 15px;
  color: #303133;
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
  font-size: 14px;
  color: #606266;
}

.conversation-item:hover {
  background: #f5f7fa;
}

.conversation-item.active {
  background: #ecf5ff;
  color: #409eff;
}

.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
  color: #f56c6c;
}

.conversation-item:hover .delete-btn {
  opacity: 1;
}

.empty-tip {
  text-align: center;
  color: #c0c4cc;
  padding: 40px 0;
  font-size: 14px;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.kb-selector {
  padding: 12px 20px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}

.selector-options {
  margin-bottom: 8px;
}

.kb-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.empty-chat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #c0c4cc;
}

.empty-chat p {
  margin-top: 12px;
  font-size: 16px;
}

.assistant-block {
  max-width: 80%;
  margin-bottom: 16px;
}

.sources-section {
  margin-bottom: 8px;
}

.sources-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #909399;
  margin-bottom: 4px;
}

.source-content {
  font-size: 12px;
  line-height: 1.6;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  margin-top: 4px;
}

.source-full {
  margin-top: 6px;
  color: #303133;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  border-top: 1px solid #e4e7ed;
  padding-top: 6px;
}

.input-area {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 16px 20px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: #f4f4f5;
  border-radius: 8px;
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #409eff;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.8); }
}
</style>
