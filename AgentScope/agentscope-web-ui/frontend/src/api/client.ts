import { toast } from 'sonner';

const configuredApiBaseUrl =
	import.meta.env.VITE_AGENTSCOPE_API_BASE_URL ||
	import.meta.env.VITE_DEFAULT_SERVER_URL ||
	'/agentscope-api';

/**
 * Resolve the deployment-owned AgentScope API endpoint.
 *
 * The default is a same-origin reverse-proxy path so management users never
 * need to know an internal host or port. An absolute URL remains supported as
 * a deployment-time override, but is never entered or stored in the browser.
 */
export const getBaseUrl = () =>
	new URL(configuredApiBaseUrl, window.location.origin).toString().replace(/\/+$/, '');

export const getApiUrl = (path: string) => new URL(path.replace(/^\/+/, ''), `${getBaseUrl()}/`);

export const getAuthToken = () => localStorage.getItem('auth_token') ?? '';

export interface ManagementLoginResponse {
	access_token: string;
	token_type: 'bearer';
	expires_in: number;
	username: string;
}

export function clearAuthSession() {
	localStorage.removeItem('auth_token');
	localStorage.removeItem('auth_expires_at');
}

export function hasValidAuthSession() {
	// Migrate away from the old user-entered connection setting.
	localStorage.removeItem('server_url');
	const token = getAuthToken();
	const expiresAt = Number(localStorage.getItem('auth_expires_at') ?? 0);
	if (!token || !Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
		clearAuthSession();
		return false;
	}
	return true;
}

/**
 * Structured error thrown for non-2xx HTTP responses.
 * `message` contains the human-readable detail extracted from the backend.
 */
export class ApiError extends Error {
	readonly status: number;
	readonly detail: string;

	constructor(status: number, detail: string) {
		super(detail);
		this.name = 'ApiError';
		this.status = status;
		this.detail = detail;
	}
}

interface RequestOptions {
	method?: string;
	body?: unknown;
	params?: Record<string, string>;
	/** When true, suppresses the automatic error toast. Useful when the caller shows its own inline error UI. */
	silent?: boolean;
}

function buildHeaders(hasBody: boolean): Record<string, string> {
	const headers: Record<string, string> = {};
	const token = getAuthToken();
	if (token) headers.Authorization = `Bearer ${token}`;
	if (hasBody) headers['Content-Type'] = 'application/json';
	return headers;
}

export async function loginManagement(
	username: string,
	password: string,
): Promise<ManagementLoginResponse> {
	const res = await fetch(getApiUrl('/auth/login'), {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ username: username.trim(), password }),
	});
	if (!res.ok) {
		throw new ApiError(res.status, await extractErrorDetail(res));
	}
	const payload = (await res.json()) as ManagementLoginResponse;
	localStorage.setItem('auth_token', payload.access_token);
	localStorage.setItem('auth_username', payload.username);
	localStorage.setItem('auth_expires_at', String(Date.now() + payload.expires_in * 1000));
	// Remove the user-entered endpoint persisted by older builds.
	localStorage.removeItem('server_url');
	// Remove the pre-authentication pseudo identity used by older builds.
	localStorage.removeItem('username');
	return payload;
}

/** Parse the response body and extract the `detail` field if the backend returned JSON. */
async function extractErrorDetail(res: Response): Promise<string> {
	const text = await res.text();
	try {
		const json = JSON.parse(text) as { detail?: unknown };
		if (typeof json.detail === 'string') return json.detail;
		if (json.detail !== undefined) return JSON.stringify(json.detail);
	} catch {
		// not JSON – fall through
	}
	return text || res.statusText;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
	const { method = 'GET', body, params, silent = false } = options;
	const url = getApiUrl(path);
	if (params) {
		Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
	}

	const res = await fetch(url.toString(), {
		method,
		headers: buildHeaders(body !== undefined),
		body: body ? JSON.stringify(body) : undefined,
	});

	if (!res.ok) {
		const detail = await extractErrorDetail(res);
		const error = new ApiError(res.status, detail);
		if (res.status === 401) {
			clearAuthSession();
			if (window.location.pathname !== '/setup') {
				window.location.assign('/setup');
			}
		}
		if (!silent) toast.error(detail);
		throw error;
	}

	if (res.status === 204) return undefined as T;
	return res.json() as Promise<T>;
}

async function streamRequest(
	path: string,
	options: RequestOptions & { signal?: AbortSignal } = {},
): Promise<Response> {
	const { method = 'GET', body, params, signal, silent = false } = options;
	const url = getApiUrl(path);
	if (params) {
		Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
	}

	const res = await fetch(url.toString(), {
		method,
		headers: buildHeaders(body !== undefined),
		body: body ? JSON.stringify(body) : undefined,
		signal,
	});

	if (!res.ok) {
		const detail = await extractErrorDetail(res);
		const error = new ApiError(res.status, detail);
		if (res.status === 401) {
			clearAuthSession();
			if (window.location.pathname !== '/setup') {
				window.location.assign('/setup');
			}
		}
		if (!silent) toast.error(detail);
		throw error;
	}

	return res;
}

export const client = {
	get: <T>(path: string, params?: Record<string, string>) =>
		request<T>(path, { method: 'GET', params }),
	post: <T>(
		path: string,
		body?: unknown,
		params?: Record<string, string>,
		options?: { silent?: boolean },
	) => request<T>(path, { method: 'POST', body, params, silent: options?.silent }),
	put: <T>(
		path: string,
		body?: unknown,
		params?: Record<string, string>,
		options?: { silent?: boolean },
	) => request<T>(path, { method: 'PUT', body, params, silent: options?.silent }),
	patch: <T>(
		path: string,
		body?: unknown,
		params?: Record<string, string>,
		options?: { silent?: boolean },
	) => request<T>(path, { method: 'PATCH', body, params, silent: options?.silent }),
	delete: <T = void>(path: string, params?: Record<string, string>) =>
		request<T>(path, { method: 'DELETE', params }),
	stream: (path: string, options?: RequestOptions & { signal?: AbortSignal }) =>
		streamRequest(path, options),
};
