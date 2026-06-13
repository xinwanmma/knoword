import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：自动附加 JWT token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：统一错误处理
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      const { status, data } = error.response
      if (status === 401) {
        localStorage.removeItem('token')
        router.push('/login')
        ElMessage.error('登录已过期，请重新登录')
      } else if (status === 403) {
        ElMessage.error('没有权限执行此操作')
      } else {
        ElMessage.error(data.detail || '请求失败')
      }
    } else {
      ElMessage.error('网络连接失败')
    }
    return Promise.reject(error)
  }
)

export default api

// ==================== API 方法 ====================

// 认证
export const authAPI = {
  register: (data) => api.post('/auth/register', data),
  login: (data) => api.post('/auth/login', data),
  getMe: () => api.get('/auth/me'),
}

// 知识库
export const kbAPI = {
  list: () => api.get('/kb'),
  get: (id) => api.get(`/kb/${id}`),
  create: (data) => api.post('/kb', data),
  update: (id, data) => api.put(`/kb/${id}`, data),
  delete: (id) => api.delete(`/kb/${id}`),
}

// 文档
export const docAPI = {
  upload: (kbId, files) => {
    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))
    return api.post(`/documents/upload?kb_id=${kbId}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
  getStatus: (docId) => api.get(`/documents/${docId}/status`),
  delete: (docId) => api.delete(`/documents/${docId}`),
  reindex: (docId) => api.post(`/documents/${docId}/reindex`),
  listByKb: (kbId) => api.get(`/documents/kb/${kbId}`),
}

// 分类
export const categoryAPI = {
  list: () => api.get('/categories'),
  create: (data) => api.post('/categories', data),
}

// 对话（SSE 流式）
export const chatAPI = {
  stream: (data, { onToken, onSources, onDone, onError, onAgent, onCache, onStatus }) => {
    const token = localStorage.getItem('token')
    const controller = new AbortController()

    fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const err = await response.json()
          onError(err.detail || '请求失败')
          return
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          let eventType = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim()
            } else if (line.startsWith('data: ')) {
              const rawData = line.slice(6)
              if (eventType === 'token') {
                // token 是纯文本，不需要 JSON.parse
                onToken(rawData)
              } else {
                try {
                  const parsed = JSON.parse(rawData)
                  if (eventType === 'sources') onSources(parsed)
                  else if (eventType === 'agent') onAgent && onAgent(parsed)
                  else if (eventType === 'status') onStatus && onStatus(parsed)
                  else if (eventType === 'cache') onCache && onCache(parsed)
                  else if (eventType === 'done') onDone(parsed)
                  else if (eventType === 'error') onError(parsed.message || '生成失败')
                } catch {
                  // non-token events should be valid JSON
                }
              }
            }
          }
        }
      })
      .catch((err) => {
        if (err.name !== 'AbortError') onError(err.message)
      })

    return controller
  },

  history: () => api.get('/chat/history'),
  getMessages: (convId) => api.get(`/chat/history/${convId}`),
  deleteConversation: (convId) => api.delete(`/chat/history/${convId}`),
}

// 健康检查
export const healthAPI = {
  check: () => api.get('/health'),
}

// 管理员
export const adminAPI = {
  listUsers: () => api.get('/auth/admin/users'),
  toggleAdmin: (userId) => api.put(`/auth/admin/users/${userId}/toggle-admin`),
}

// Store 记忆
export const storeAPI = {
  list: (namespace) => api.get('/store', { params: { namespace } }),
  get: (key, namespace = 'default') => api.get(`/store/${key}`, { params: { namespace } }),
  put: (key, value, namespace = 'default') => api.put('/store', { key, value, namespace }),
  delete: (key, namespace = 'default') => api.delete(`/store/${key}`, { params: { namespace } }),
  clear: (namespace) => api.delete('/store', { params: { namespace } }),
}
