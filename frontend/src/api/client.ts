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
      sessionStorage.removeItem('access_token')
      sessionStorage.removeItem('logged_in')
    }
    return Promise.reject(error)
  },
)

export default api
