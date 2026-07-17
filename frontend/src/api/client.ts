import axios from 'axios'

export type ApiEnvelope<T> = { success: boolean; data: T; message: string }

const apiBaseUrl = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env?.VITE_API_BASE_URL || '/api'
const api = axios.create({ baseURL: apiBaseUrl, timeout: 15_000 })

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  response => response,
  (error) => {
    if (error.response?.status === 401) {
      const requestToken = String(error.config?.headers?.Authorization || '').replace(/^Bearer\s+/i, '')
      // 登录切换期间，旧请求可能比新登录响应更晚返回；不能用旧请求的 401 清掉新令牌。
      if (!requestToken || requestToken === sessionStorage.getItem('access_token')) {
        sessionStorage.removeItem('access_token')
        sessionStorage.removeItem('logged_in')
      }
    }
    return Promise.reject(error)
  },
)

export default api
